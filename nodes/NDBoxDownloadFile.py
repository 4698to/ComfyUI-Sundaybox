"""
NDBox_DownloadFile Node - Register a file on the server and
expose a safe download_id + filename to the frontend UI.
The browser then calls a dedicated HTTP route to stream
the file, without ever seeing the raw server path.
"""

from pathlib import Path
from typing import Tuple
import os
import uuid
import time
import folder_paths
from aiohttp import web
from server import PromptServer

# Simple in-memory registry for download IDs -> file paths
_DOWNLOAD_REGISTRY = {}
_DOWNLOAD_REGISTRY_TTL = 60 * 30  # 30 minutes


def _cleanup_expired_downloads():
    now = time.time()
    expired_ids = [
        token
        for token, item in _DOWNLOAD_REGISTRY.items()
        if now - item.get("time", 0) > _DOWNLOAD_REGISTRY_TTL
    ]
    for token in expired_ids:
        _DOWNLOAD_REGISTRY.pop(token, None)

def _get_public_user_root(user_id: str) -> str | None:
    getter = getattr(folder_paths, "get_public_user_directory", None)
    if callable(getter):
        return getter(user_id)
    uid = (user_id or "").strip()
    if not uid or uid.startswith("__"):
        return None
    user_base = getattr(folder_paths, "get_user_directory", None)
    if not callable(user_base):
        return None
    return os.path.join(user_base(), uid)


def _safe_join_under_base(base_dir: str, relative_path: str) -> str | None:
    """
    Join base_dir with a relative path and return absolute path only if it stays under base_dir.
    Rejects absolute paths and path-traversal escapes.
    """
    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return None
    if os.path.isabs(rel):
        return None
    base = os.path.abspath(base_dir)
    candidate = os.path.abspath(os.path.join(base, *rel.split("/")))
    try:
        if os.path.commonpath([base, candidate]) != base:
            return None
    except ValueError:
        return None
    return candidate


@PromptServer.instance.routes.get("/NDBox/download_file_by_filepath")
async def NDBox_download_file_by_filepath(request):
    """
    Stream a file under ComfyUI input / output / user directory.

    Query:
      - target_type: input | output | user_data (alias: upload_target, default output)
      - file_path: relative path, e.g. 3d/xxx.npz or output/3d/xxx.npz (prefix stripped when matching target)
      - user_id: for user_data only, default \"default\" (passed to folder_paths.get_public_user_directory)
    """
    try:
        q = request.rel_url.query
        target_type = (q.get("target_type") or q.get("upload_target") or "output").strip().lower()
        raw = (q.get("file_path") or "").strip()
        user_id = (q.get("user_id") or "default").strip() or "default"

        if not raw:
            return web.json_response({"ok": False, "error": "file_path is required"}, status=400)

        rel = raw.replace("\\", "/").strip()
        if os.path.isabs(rel):
            return web.json_response({"ok": False, "error": "file_path must be relative"}, status=400)

        full_path: str | None = None
        if target_type == "input":
            base = folder_paths.get_input_directory()
            if rel.lower().startswith("input/"):
                rel = rel[6:].lstrip("/")
            full_path = _safe_join_under_base(base, rel)
        elif target_type == "output":
            base = folder_paths.get_output_directory()
            if rel.lower().startswith("output/"):
                rel = rel[7:].lstrip("/")
            full_path = _safe_join_under_base(base, rel)
        elif target_type == "user_data":
            user_root = _get_public_user_root(user_id)
            if not user_root:
                return web.json_response({"ok": False, "error": "invalid user_id"}, status=400)
            if rel.lower().startswith("user_data/"):
                rel = rel[11:].lstrip("/")
            full_path = _safe_join_under_base(user_root, rel)
        else:
            return web.json_response(
                {"ok": False, "error": f"unsupported target_type: {target_type}"},
                status=400,
            )

        if not full_path or not os.path.isfile(full_path):
            return web.json_response({"ok": False, "error": "file not found on server"}, status=404)

        filename = os.path.basename(full_path) or "download.bin"
        return web.FileResponse(
            path=full_path,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

@PromptServer.instance.routes.get("/NDBox/download_file/{download_id}")
async def NDBox_download_file(request):
    """
    Stream a registered file using a short-lived download_id.
    """
    try:
        _cleanup_expired_downloads()
        download_id = request.match_info.get("download_id", "")
        item = _DOWNLOAD_REGISTRY.get(download_id)
        if not item:
            return web.json_response({"ok": False, "error": "download_id not found or expired"}, status=404)

        file_path = item.get("path", "")
        if not file_path or not os.path.isfile(file_path):
            _DOWNLOAD_REGISTRY.pop(download_id, None)
            return web.json_response({"ok": False, "error": "file not found on server"}, status=404)

        filename = os.path.basename(file_path) or "download.bin"
        # Single-use token: prevent stale link reuse.
        _DOWNLOAD_REGISTRY.pop(download_id, None)
        return web.FileResponse(path=file_path, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

def _build_download_url(download_id: str | None) -> str:
    """
    Build a URL for GET /NDBox/download_file/{download_id}.
    Prefer absolute http://host:port/... when comfy.cli_args is available;
    otherwise return a root-relative path (same origin as the ComfyUI UI).
    """
    if not download_id:
        return ""
    path = f"/NDBox/download_file/{download_id}"
    try:
        import comfy.cli_args as cli_args

        args = cli_args.args
        listen = getattr(args, "listen", None) or "127.0.0.1"
        port = int(getattr(args, "port", 8188))
        if listen in ("0.0.0.0", "::"):
            listen = "127.0.0.1"
        # IPv6 literal host must be bracketed in URLs
        if ":" in listen and not listen.startswith("["):
            host = f"[{listen}]"
        else:
            host = listen
        return f"http://{host}:{port}{path}"
    except Exception:
        return path


def register_download_path(file_path: str) -> str:
    """
    Register a file path and return a short download_id.
    This avoids exposing raw paths to the frontend.
    """
    # Normalize path
    full_path = os.path.abspath(file_path)
    download_id = uuid.uuid4().hex
    _DOWNLOAD_REGISTRY[download_id] = {
        "path": full_path,
        "time": time.time(),
    }
    return download_id

class NDBox_DownloadFile:
    """
    Utility node that exposes a *download token* to frontend,
    not the real filesystem path.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "file_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "要下载的文件绝对路径（仅在服务端使用，不会直接暴露给前端）。"
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("info", "download_url")
    FUNCTION = "prepare_download"
    OUTPUT_NODE = True
    CATEGORY = "Sundaybox/Tools"

    def prepare_download(
        self,
        file_path: str,
    ) -> Tuple[str, str]:
        """
        Validate the file path and register it in the download registry.
        Frontend will receive (filename, download_id, exists) and should
        call /NDBox/download_file/{download_id} to actually download.
        """
        try:
            print("[NDBox_DownloadFile] Preparing file content for download UI...")

            if not file_path or not str(file_path).strip():
                raise ValueError("file_path 为空，请提供要下载的文件路径。")
            else:
                print(f"[NDBox_DownloadFile] file_path={file_path}")
            raw = str(file_path).strip().replace("\\", "/")
            
            input_base = Path(folder_paths.get_input_directory()).resolve()
            output_base = Path(folder_paths.get_output_directory()).resolve()

            print(f"[NDBox_DownloadFile] input_base={input_base}, output_base={output_base}")
            # 1) 先按原始路径解析（绝对或相对）
            p = Path(raw).expanduser().resolve()
            if not (p.exists() and p.is_file()):
                # 2) 如果不存在，尝试前面拼接 output_base
                p_output = (output_base / raw).resolve()
                if p_output.exists() and p_output.is_file():
                    p = p_output
                else:
                    # 3) 如果还不存在，再尝试前面拼接 input_base
                    p_input = (input_base / raw).resolve()
                    if p_input.exists() and p_input.is_file():
                        p = p_input

            exists = p.exists() and p.is_file()
            file_name = p.name if exists else p.name

            file_size = None
            if exists:
                try:
                    file_size = p.stat().st_size
                except OSError:
                    file_size = None

            download_id = None
            if exists:
                download_id = register_download_path(str(p))

            download_url = _build_download_url(download_id)

            print(f"[NDBox_DownloadFile] file_path={p.absolute()}, exists={exists}, size={file_size}, download_id={download_id}")

            info = (
                "NDBox_DownloadFile Ready\n"
                f"File name: {file_name}\n"
                f"File path: {p.absolute()}\n"
                f"Exists on server: {exists}\n"
                f"File size (bytes): {file_size}\n"
                f"Download id: {download_id}\n"
            )

            # 只把文件名和 download_id 传给前端，不暴露真实路径
            return {
                "ui": {
                    "file_name": [file_name],
                    "download_id": [download_id],
                    "file_exists": [bool(exists)],
                    "file_size_bytes": [file_size],
                    "file_path": [str(p.absolute())],
                },
                "result": (info, download_url),
            }

        except Exception as e:
            error_msg = f"NDBox_DownloadFile failed: {str(e)}"
            print(error_msg)
            return {
                "ui": {
                    "file_name": [""],
                    "download_id": [None],
                    "file_exists": [False],
                },
                "result": (error_msg, ""),
            }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Always re-run when input changes so UI can update
        return float("nan")


NODE_CLASS_MAPPINGS = {
    "NDBox_DownloadFile": NDBox_DownloadFile,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NDBox_DownloadFile": "NDBox Download File",
}

