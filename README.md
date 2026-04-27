# ComfyUI-Sundaybox

![](assets/Snipaste_2026-04-27_16-41-58.png)

`ComfyUI-Sundaybox` 是一个面向 ComfyUI 的实用插件，当前提供两个节点：

- `NDBox_UploadFiles`：在节点面板内上传本地文件到 ComfyUI 目录。
- `NDBox_DownloadFile`：通过安全下载令牌下载服务端文件（不直接暴露真实路径）。

## 功能特性

- 节点内嵌前端 UI（iframe）完成上传/下载操作。
- 上传支持多种扩展名过滤：`any`、`npz`、`npy`、`json`、`txt`、`csv`、`bvh`、`fbx`、`obj`、`glb`。
- 上传目标支持 `output` / `input`。
- 下载使用短期 `download_id`，前端不暴露服务器绝对路径。
- 历史文件列表支持按类型刷新，上传后可立即更新下拉项。

## 目录结构

```text
ComfyUI-Sundaybox/
├─ __init__.py
├─ nodes/
│  ├─ NDBoxUploadFile.py
│  └─ NDBoxDownloadFile.py
└─ web/
   ├─ NDBoxUploadFile.html
   ├─ NDBoxUploadFile.js
   ├─ NDBoxDownloadFile.html
   └─ NDBoxDownloadFile.js
```

## 安装方式

1. 将本仓库放到 ComfyUI 的 `custom_nodes` 目录下：
   - `ComfyUI/custom_nodes/ComfyUI-Sundaybox`
2. 重启 ComfyUI。
3. 打开前端后搜索节点：
   - `NDBox Upload NPZ`
   - `NDBox Download File`

## 节点说明

### 1) NDBox_UploadFiles

用于上传本地文件并输出相对路径（例如 `output/3d/demo.npz`）。

主要输入参数：

- `upload_target`：上传到 `output` 或 `input`。
- `upload_subdir`：当 `upload_target=input` 时可选子目录。
- `file_type`：上传后缀限制。
- `file_name`：历史文件下拉项。
- `file_path`：当前文件路径（可由上传自动写入）。

输出：

- `file_path`（`STRING`）：上传后的相对路径或当前选中文件路径。

### 2) NDBox_DownloadFile

输入服务器文件路径，生成下载信息并在前端提供下载按钮。

主要输入参数：

- `file_path`：要下载的文件路径（可绝对路径，也可相对 `output/input` 路径）。

输出：

- `info`（`STRING`）：包含文件名、存在性、大小、下载令牌等信息。

## HTTP 路由

插件会注册以下路由：

- `POST /NDBox/upload_files`：上传文件。
- `GET /NDBox/list_uploaded_files?file_type=...`：获取历史文件列表。
- `GET /NDBox/list_input_subdirs`：获取 input 子目录列表。
- `GET /NDBox/download_file/{download_id}`：按下载令牌下载文件。

## 使用建议

- 上传节点建议新建后再使用，确保前端脚本和 iframe 已更新到最新版本。
- 页面更新后若 UI 未同步，建议浏览器强制刷新（`Ctrl+F5`）。
- `download_id` 设计为短期/一次性使用，适合前端安全下载场景。


## 开发备注

- 插件入口通过 `__init__.py` 导出：
  - `NODE_CLASS_MAPPINGS`
  - `NODE_DISPLAY_NAME_MAPPINGS`
  - `WEB_DIRECTORY = "web"`
- 前端扩展名：
  - `NDBox.UploadFiles`
  - `NDBox.DownloadFile`

## 许可


