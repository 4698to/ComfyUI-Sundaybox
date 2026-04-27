import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "NDBox.UploadFiles",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const nodeName = String(nodeData?.name || "");
        if (nodeName !== "NDBox_UploadFiles" && nodeName !== "NDBox Upload NPZ") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            try {
                node.size = [460, 340];
            } catch (e) {
                console.warn("[NDBox_UploadFiles] resize failed:", e);
            }

            const iframe = document.createElement("iframe");
            iframe.src = `/extensions/ComfyUI-Sundaybox/NDBoxUploadFile.html?v=${Date.now()}`;
            iframe.style.cssText = "width:100%; height:220px; border:0; background:#111;";
            iframe.setAttribute("scrolling", "no");

            let domWidget = null;
            if (typeof node.addDOMWidget === "function") {
                try {
                    domWidget = node.addDOMWidget("Upload Files", "ndbox_upload_files", iframe, {
                        serialize: false,
                    });
                } catch (e) {
                    console.warn("[NDBox_UploadFiles] addDOMWidget failed, fallback to node.html:", e);
                }
            }
            if (!domWidget) {
                node.html = iframe;
            } else {
                domWidget.serialize = false;
                domWidget.computeSize = (width) => [Math.max(260, width || 420), 230];
            }

            const getPathWidget = () => {
                const widgets = node.widgets || [];
                return widgets.find((w) => w && w.name === "file_path") || null;
            };

            const getTypeWidget = () => {
                const widgets = node.widgets || [];
                return widgets.find((w) => w && w.name === "file_type") || null;
            };

            const getTargetWidget = () => {
                const widgets = node.widgets || [];
                return widgets.find((w) => w && w.name === "upload_target") || null;
            };

            const getSubdirWidget = () => {
                const widgets = node.widgets || [];
                return widgets.find((w) => w && w.name === "upload_subdir") || null;
            };

            const getNameWidget = () => {
                const widgets = node.widgets || [];
                return widgets.find((w) => w && w.name === "file_name") || null;
            };

            const refreshHistoryByType = async (fileTypeValue) => {
                const nameWidget = getNameWidget();
                if (!nameWidget) return;
                const fileType = typeof fileTypeValue === "string" && fileTypeValue ? fileTypeValue : "any";
                try {
                    const resp = await fetch(
                        `/NDBox/list_uploaded_files?file_type=${encodeURIComponent(fileType)}`,
                        { method: "GET" }
                    );
                    const data = await resp.json();
                    if (!resp.ok || !data?.ok || !Array.isArray(data.files)) return;
                    const values = Array.isArray(data.files) ? data.files.slice() : [];
                    if (!values.includes("none")) {
                        values.unshift("none");
                    }
                    if (!nameWidget.options) {
                        nameWidget.options = {};
                    }
                    nameWidget.options.values = values;
                    if (!values.includes(nameWidget.value)) {
                        nameWidget.value = values[0];
                        if (typeof nameWidget.callback === "function") {
                            nameWidget.callback(nameWidget.value);
                        }
                    }
                    node.setDirtyCanvas(true, true);
                } catch (e) {
                    console.warn("[NDBox_UploadFiles] refresh history failed:", e);
                }
            };

            const sendStateToIframe = (pathValue, fileTypeValue, uploadTargetValue, uploadSubdirValue) => {
                if (!iframe.contentWindow) return;
                iframe.contentWindow.postMessage(
                    {
                        type: "ndbox_files_state",
                        npzPath: pathValue || "",
                        fileType: fileTypeValue || "any",
                        uploadTarget: uploadTargetValue || "output",
                        uploadSubdir: uploadSubdirValue || "3d",
                    },
                    "*"
                );
            };

            const syncCurrentState = () => {
                const pathWidget = getPathWidget();
                const typeWidget = getTypeWidget();
                const targetWidget = getTargetWidget();
                const subdirWidget = getSubdirWidget();
                sendStateToIframe(
                    pathWidget ? pathWidget.value : "",
                    typeWidget ? typeWidget.value : "any",
                    targetWidget ? targetWidget.value : "output",
                    subdirWidget ? subdirWidget.value : "3d"
                );
            };

            window.addEventListener("message", (event) => {
                const data = event.data || {};
                if (data.type === "ndbox_files_uploaded") {
                    const uploadedPath =
                        typeof data.filePath === "string"
                            ? data.filePath
                            : (typeof data.npzPath === "string" ? data.npzPath : "");
                    if (!uploadedPath) return;

                    const pathWidget = getPathWidget();
                    if (!pathWidget) return;

                    pathWidget.value = uploadedPath;
                    if (typeof pathWidget.callback === "function") {
                        pathWidget.callback(uploadedPath);
                    }
                    if (typeof data.fileType === "string") {
                        const typeWidget = getTypeWidget();
                        if (typeWidget) {
                            typeWidget.value = data.fileType;
                            if (typeof typeWidget.callback === "function") {
                                typeWidget.callback(data.fileType);
                            }
                        }
                    }
                    if (typeof data.uploadTarget === "string") {
                        const targetWidget = getTargetWidget();
                        if (targetWidget) {
                            targetWidget.value = data.uploadTarget;
                            if (typeof targetWidget.callback === "function") {
                                targetWidget.callback(data.uploadTarget);
                            }
                        }
                    }
                    if (typeof data.uploadSubdir === "string") {
                        const subdirWidget = getSubdirWidget();
                        if (subdirWidget) {
                            subdirWidget.value = data.uploadSubdir;
                            if (typeof subdirWidget.callback === "function") {
                                subdirWidget.callback(data.uploadSubdir);
                            }
                        }
                    }
                    const typeWidget = getTypeWidget();
                    refreshHistoryByType(typeWidget ? typeWidget.value : "any");
                    node.setDirtyCanvas(true, true);
                    syncCurrentState();
                    return;
                }

                if (data.type === "ndbox_files_file_type_changed" && typeof data.fileType === "string") {
                    const typeWidget = getTypeWidget();
                    if (!typeWidget) return;
                    typeWidget.value = data.fileType;
                    if (typeof typeWidget.callback === "function") {
                        typeWidget.callback(data.fileType);
                    }
                    refreshHistoryByType(data.fileType);
                    node.setDirtyCanvas(true, true);
                    syncCurrentState();
                }

                if (data.type === "ndbox_files_upload_target_changed" && typeof data.uploadTarget === "string") {
                    const targetWidget = getTargetWidget();
                    if (!targetWidget) return;
                    targetWidget.value = data.uploadTarget;
                    if (typeof targetWidget.callback === "function") {
                        targetWidget.callback(data.uploadTarget);
                    }
                    node.setDirtyCanvas(true, true);
                    syncCurrentState();
                }

                if (data.type === "ndbox_files_upload_subdir_changed" && typeof data.uploadSubdir === "string") {
                    const subdirWidget = getSubdirWidget();
                    if (!subdirWidget) return;
                    subdirWidget.value = data.uploadSubdir;
                    if (typeof subdirWidget.callback === "function") {
                        subdirWidget.callback(data.uploadSubdir);
                    }
                    node.setDirtyCanvas(true, true);
                    syncCurrentState();
                }
            });

            const origOnExecuted = node.onExecuted;
            node.onExecuted = function (output) {
                if (origOnExecuted) {
                    try {
                        origOnExecuted.apply(this, arguments);
                    } catch (e) {
                        console.warn("[NDBox_UploadFiles] original onExecuted error:", e);
                    }
                }
                const ui = output?.ui || output || {};
                const uiPath = ui?.file_path?.[0];
                if (typeof uiPath === "string") {
                    const typeWidget = getTypeWidget();
                    const targetWidget = getTargetWidget();
                    const subdirWidget = getSubdirWidget();
                    sendStateToIframe(
                        uiPath,
                        typeWidget ? typeWidget.value : "any",
                        targetWidget ? targetWidget.value : "output",
                        subdirWidget ? subdirWidget.value : "3d"
                    );
                } else {
                    syncCurrentState();
                }
            };

            const typeWidget = getTypeWidget();
            if (typeWidget && typeof typeWidget.callback === "function") {
                const originalTypeCallback = typeWidget.callback.bind(typeWidget);
                typeWidget.callback = (...args) => {
                    originalTypeCallback(...args);
                    setTimeout(syncCurrentState, 0);
                    setTimeout(() => refreshHistoryByType(typeWidget.value), 0);
                };
            }
            const targetWidget = getTargetWidget();
            if (targetWidget && typeof targetWidget.callback === "function") {
                const originalTargetCallback = targetWidget.callback.bind(targetWidget);
                targetWidget.callback = (...args) => {
                    originalTargetCallback(...args);
                    setTimeout(syncCurrentState, 0);
                };
            }
            const subdirWidget = getSubdirWidget();
            if (subdirWidget && typeof subdirWidget.callback === "function") {
                const originalSubdirCallback = subdirWidget.callback.bind(subdirWidget);
                subdirWidget.callback = (...args) => {
                    originalSubdirCallback(...args);
                    setTimeout(syncCurrentState, 0);
                };
            }

            const initialType = typeWidget ? typeWidget.value : "any";
            refreshHistoryByType(initialType);
            setTimeout(syncCurrentState, 200);
            return r;
        };
    },
});

