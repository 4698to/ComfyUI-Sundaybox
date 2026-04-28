"""
NDBox_UploadFiles Node - upload local files from web UI to
ComfyUI output/NDBox_npz directory, then output saved path.
"""

import os
import uuid
from typing import Tuple

import folder_paths
from aiohttp import web
from server import PromptServer


FILE_TYPE_ACCEPTS = {
    "any": "*/*",
    "npz": ".npz",
    "npy": ".npy",
    "json": ".json",
    "txt": ".txt",
    "csv": ".csv",
    "bvh": ".bvh",
    "fbx": ".fbx",
    "obj": ".obj",
    "glb": ".glb",
}
UPLOAD_TARGETS = ("output", "input")

LAST_UPLOADED_PATH = ""


def _safe_upload_name(filename: str) -> str:
    name = os.path.basename(filename or "").strip()
    if not name:
        name = f"upload_{uuid.uuid4().hex}"
    return name.replace("\\", "_").replace("/", "_")


def _is_extension_allowed(filename: str, file_type: str) -> bool:
    normalized_type = (file_type or "any").strip().lower()
    if normalized_type == "any":
        return True
    expected_ext = f".{normalized_type}"
    return (filename or "").lower().endswith(expected_ext)


def _filter_history_files_by_type(file_names, file_type: str):
    normalized_type = (file_type or "any").strip().lower()
    if normalized_type == "any":
        return file_names
    expected_ext = f".{normalized_type}"
    return [name for name in file_names if (name or "").lower().endswith(expected_ext)]


def _get_history_files(file_type: str):
    files = []
    # Some ComfyUI setups do not register custom folder type "3d".
    # Fall back to direct directory scan so INPUT_TYPES never crashes.
    for folder_key in ("3d", "NDBox_npz"):
        try:
            files.extend(folder_paths.get_filename_list(folder_key))
        except Exception:
            pass

    if not files:
        for base_dir in (folder_paths.get_output_directory(), folder_paths.get_input_directory()):
            for subdir in ("3d", "NDBox_npz"):
                scan_dir = os.path.join(base_dir, subdir)
                if not os.path.isdir(scan_dir):
                    continue
                try:
                    for name in os.listdir(scan_dir):
                        full_path = os.path.join(scan_dir, name)
                        if os.path.isfile(full_path):
                            files.append(name)
                except Exception:
                    pass

    files = _filter_history_files_by_type(files, file_type)
    # Keep "none" always available for old workflows and manual clear.
    uniq = []
    for name in (["none"] + files):
        if name not in uniq:
            uniq.append(name)
    return uniq


def _normalize_input_subdir(path_value: str) -> str:
    raw = (path_value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return "3d"
    normalized = os.path.normpath(raw).replace("\\", "/").strip("/")
    if normalized in ("", "."):
        return "3d"
    if normalized.startswith("..") or "/../" in f"/{normalized}/":
        return "3d"
    return normalized


def _list_input_subdirs():
    input_dir = os.path.abspath(folder_paths.get_input_directory())
    candidates = set(["3d"])
    try:
        for root, dirs, _files in os.walk(input_dir):
            rel = os.path.relpath(root, input_dir).replace("\\", "/")
            depth = 0 if rel == "." else rel.count("/") + 1
            if 1 <= depth <= 2:
                candidates.add(rel)
            if depth >= 2:
                dirs[:] = []
    except Exception:
        pass
    return sorted(candidates)


def _resolve_selected_file_path(upload_target: str, upload_subdir: str, file_name: str) -> str:
    target = (upload_target or "output").strip().lower()
    subdir = _normalize_input_subdir(upload_subdir)
    name = (file_name or "").strip().replace("\\", "/")
    if not name or name == "none":
        return ""

    if "/" in name:
        # Already a relative path-like value.
        return name

    base_dir = folder_paths.get_output_directory() if target == "output" else folder_paths.get_input_directory()
    target_subdir = "3d" if target == "output" else subdir
    candidate = os.path.join(base_dir, target_subdir, name)
    if os.path.exists(candidate):
        return f"{target}/{target_subdir}/{name}".replace("\\", "/")

    # Fallback to existing full-path lookup compatibility.
    full_path = None
    for folder_key in ("3d", "NDBox_npz"):
        try:
            resolved = folder_paths.get_full_path(folder_key, name)
        except Exception:
            resolved = None
        if resolved and os.path.exists(resolved):
            full_path = resolved
            break

    if full_path and os.path.exists(full_path):
        output_dir = os.path.abspath(folder_paths.get_output_directory()).replace("\\", "/")
        input_dir = os.path.abspath(folder_paths.get_input_directory()).replace("\\", "/")
        full_norm = os.path.abspath(full_path).replace("\\", "/")
        if full_norm.startswith(output_dir + "/"):
            rel = full_norm[len(output_dir) + 1:]
            return f"output/{rel}"
        if full_norm.startswith(input_dir + "/"):
            rel = full_norm[len(input_dir) + 1:]
            return f"input/{rel}"
        return full_norm

    return name


@PromptServer.instance.routes.post("/NDBox/upload_files")
async def NDBox_upload_npz(request):
    global LAST_UPLOADED_PATH
    try:
        reader = await request.multipart()
        file_type = "any"
        upload_target = "output"
        upload_subdir = "3d"
        original_name = ""
        file_bytes = bytearray()

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "file" and part.filename:
                original_name = part.filename
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    file_bytes.extend(chunk)
            elif part.name == "file_type":
                file_type = (await part.text()).strip().lower() or "any"
            elif part.name == "upload_target":
                upload_target = (await part.text()).strip().lower() or "output"
            elif part.name == "upload_subdir":
                upload_subdir = _normalize_input_subdir(await part.text())

        if not original_name:
            return web.json_response({"ok": False, "error": "No file provided."}, status=400)
        if len(file_bytes) == 0:
            return web.json_response({"ok": False, "error": "Uploaded file is empty."}, status=400)

        if file_type not in FILE_TYPE_ACCEPTS:
            return web.json_response({"ok": False, "error": f"Unsupported file_type: {file_type}"}, status=400)
        if upload_target not in UPLOAD_TARGETS:
            return web.json_response(
                {"ok": False, "error": f"Unsupported upload_target: {upload_target}"},
                status=400,
            )
        if not _is_extension_allowed(original_name, file_type):
            return web.json_response(
                {"ok": False, "error": f"File extension does not match selected type: {file_type}"},
                status=400,
            )

        base_dir = (
            folder_paths.get_output_directory()
            if upload_target == "output"
            else folder_paths.get_input_directory()
        )
        target_subdir = "3d" if upload_target == "output" else _normalize_input_subdir(upload_subdir)
        target_dir = os.path.join(base_dir, target_subdir)
        os.makedirs(target_dir, exist_ok=True)

        safe_name = _safe_upload_name(original_name)
        final_path = os.path.join(target_dir, safe_name)
        if os.path.exists(final_path):
            stem, ext = os.path.splitext(safe_name)
            safe_name = f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
            final_path = os.path.join(target_dir, safe_name)

        with open(final_path, "wb") as f:
            f.write(file_bytes)

        rel_path = f"{upload_target}/{target_subdir}/{safe_name}".replace("\\", "/")
        LAST_UPLOADED_PATH = rel_path
        return web.json_response({"ok": True, "file_path": rel_path, "size": len(file_bytes)})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/NDBox/list_uploaded_files")
async def NDBox_list_uploaded_files(request):
    try:
        file_type = (request.query.get("file_type", "any") or "any").strip().lower()
        if file_type not in FILE_TYPE_ACCEPTS:
            return web.json_response({"ok": False, "error": f"Unsupported file_type: {file_type}"}, status=400)
        return web.json_response({"ok": True, "files": _get_history_files(file_type)})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/NDBox/list_input_subdirs")
async def NDBox_list_input_subdirs(request):
    try:
        return web.json_response({"ok": True, "subdirs": _list_input_subdirs()})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


@PromptServer.instance.routes.get("/NDBox/resolve_file_path")
async def NDBox_resolve_file_path(request):
    try:
        upload_target = (request.query.get("upload_target", "output") or "output").strip().lower()
        upload_subdir = request.query.get("upload_subdir", "3d") or "3d"
        file_name = request.query.get("file_name", "none") or "none"
        path = _resolve_selected_file_path(upload_target, upload_subdir, file_name)
        return web.json_response({"ok": True, "file_path": path})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


class NDBox_UploadFiles:
    @classmethod
    def INPUT_TYPES(cls):
        default_type = "any"
        file_files = _get_history_files(default_type)
        return {
            "required": {
                "upload_target": (
                    list(UPLOAD_TARGETS),
                    {
                        "default": "output",
                        "tooltip": "上传目标目录：output 或 input 下的 NDBox_npz。",
                    },
                ),
                "upload_subdir": (
                    _list_input_subdirs(),
                    {
                        "default": "NDBox_npz",
                        "tooltip": "当 upload_target=input 时生效，可选 input 下一级/二级子目录。",
                    },
                ),
                "file_type": (
                    list(FILE_TYPE_ACCEPTS.keys()),
                    {
                        "default": default_type,
                        "tooltip": "上传文件类型过滤；any 代表允许任意后缀。",
                    },
                ),
                "file_name": (
                    file_files,
                    {
                        "tooltip": "历史文件下拉列表（output/input 的 NDBox_npz）。",
                    },
                ),
                "file_path": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "通过上传自动写入；若为空则使用 file_name。格式: output/3d/xxx.ext",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "get_file_path"
    CATEGORY = "Sundaybox/Tools"
    OUTPUT_NODE = True

    def get_file_path(self, *args, **kwargs) -> Tuple[str]:
        global LAST_UPLOADED_PATH
        # Compatible with both old workflows (without file_type)
        # and new workflows (upload_target + upload_subdir + file_type + npz_name + npz_path).
        upload_target = "output"
        upload_subdir = "3d"
        file_type = "any"
        file_name = "none"
        file_path = ""

        if len(args) == 2:
            file_name, file_path = args
        elif len(args) >= 3:
            if len(args) >= 5:
                upload_target, upload_subdir, file_type, file_name, file_path = args[:5]
            else:
                file_type, file_name, file_path = args[:3]

        if "upload_target" in kwargs:
            upload_target = kwargs.get("upload_target", "output")
        if "upload_subdir" in kwargs:
            upload_subdir = kwargs.get("upload_subdir", "3d")

        if "file_type" in kwargs:
            file_type = kwargs.get("file_type", "any")
        if "file_name" in kwargs:
            file_name = kwargs.get("file_name", "none")
        if "npz_path" in kwargs:
            file_path = kwargs.get("file_path", "")

        _ = (upload_target, upload_subdir, file_type)
        path = (file_path or "").strip().replace("\\", "/")

        if not path and LAST_UPLOADED_PATH:
            path = LAST_UPLOADED_PATH

        if not path and file_name and file_name != "none":
            path = _resolve_selected_file_path(upload_target, upload_subdir, file_name)

        return {"ui": {"file_path": [path]}, "result": (path,)}


NODE_CLASS_MAPPINGS = {
    "NDBox_UploadFiles": NDBox_UploadFiles,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NDBox_UploadFiles": "NDBox Upload Files",
}

