from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Callable, Optional
import uuid

import httpx
from server.config import settings
from agent.models import ErrorDetail

logger = logging.getLogger(__name__)

class ComfyUIClient:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.host = host or settings.comfyui_host
        self.port = port or settings.comfyui_port
        self.client_id = client_id or str(uuid.uuid4())
        self.base_url = f"http://{self.host}:{self.port}"
        self.mock_mode = mock_mode if mock_mode is not None else settings.comfyui_mock_mode

    async def get_object_info(self) -> dict[str, Any]:
        """Fetch available nodes from ComfyUI /object_info."""
        if self.mock_mode:
            # Return standard nodes mock
            return {
                "KSampler": {},
                "CheckpointLoaderSimple": {},
                "EmptyLatentImage": {},
                "CLIPTextEncode": {},
                "VAEDecode": {},
                "SaveImage": {},
                "WanVideoModelLoader": {},
                "LoadImage": {},
                "WanVideoSampler": {},
                "VHS_VideoCombine": {},
                "CogVideoModelLoader": {},
                "CogVideoSampler": {}
            }
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.get(f"{self.base_url}/object_info")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get object_info from ComfyUI: {e}")
            return {}

    async def submit_prompt(
        self,
        workflow: dict[str, Any],
        max_retries: int = 2
    ) -> tuple[Optional[str], Optional[ErrorDetail]]:
        """Submit workflow to ComfyUI POST /prompt with retries."""
        payload = {
            "prompt": workflow,
            "client_id": self.client_id
        }

        if self.mock_mode:
            mock_prompt_id = f"mock_{uuid.uuid4().hex[:12]}"
            logger.info(f"ComfyUI mock mode active: generated prompt_id {mock_prompt_id}")
            return mock_prompt_id, None

        # Real execution with exponential backoff
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
                    resp = await client.post(f"{self.base_url}/prompt", json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        prompt_id = data.get("prompt_id")
                        if prompt_id:
                            return prompt_id, None
                        return None, ErrorDetail(
                            code="COMFYUI_INVALID_RESPONSE",
                            message="ComfyUI 响应中缺少 prompt_id",
                            details={"response": data},
                            retryable=False,
                        )
                    else:
                        err_text = resp.text[:4000]
                        if "node_errors" in err_text:
                            return None, ErrorDetail(
                                code="COMFYUI_NODE_ERROR",
                                message="ComfyUI 工作流节点执行参数验证错误",
                                details={"response": err_text},
                                retryable=False,
                                suggested_action="请检查工作流中各节点的模型名称或参数格式",
                            )
                        if attempt == max_retries:
                            return None, ErrorDetail(
                                code="COMFYUI_HTTP_ERROR",
                                message=f"ComfyUI HTTP {resp.status_code}: {err_text}",
                                retryable=False,
                            )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt == max_retries:
                    return None, ErrorDetail(
                        code="COMFYUI_CONNECTION_ERROR",
                        message=f"无法连接到 ComfyUI 服务 ({self.base_url}): {e}",
                        retryable=True,
                        suggested_action="请检查 ComfyUI 是否已启动，或设置 COMFYUI_MOCK_MODE=true 进行本地仿真测试",
                    )
                await asyncio.sleep(1.0 * (2 ** attempt))

        return None, ErrorDetail(code="COMFYUI_UNKNOWN_ERROR", message="Unknown error submitting to ComfyUI")

    async def wait_for_completion(
        self,
        prompt_id: str,
        timeout_seconds: int = 300,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[ErrorDetail]]:
        """Wait for prompt execution to complete."""
        # Check mock mode
        if self.mock_mode:
            for step in range(1, 4):
                if progress_callback:
                    progress_callback({"step": step, "max_steps": 3, "percent": int(step * 33.3)})

            mock_result = {
                "prompt_id": prompt_id,
                "outputs": {
                    "output_node": {
                        "videos": [{"filename": f"{prompt_id}.mp4", "subfolder": "mock", "type": "output"}],
                        "images": [{"filename": f"{prompt_id}.png", "subfolder": "mock", "type": "output"}]
                    }
                },
                "status": "completed"
            }
            return mock_result, None

        # Real execution: poll /history/{prompt_id}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                    resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        if prompt_id in data:
                            history_item = data[prompt_id]
                            # Check status
                            status_obj = history_item.get("status", {})
                            if status_obj.get("completed", False):
                                return history_item, None
                            elif status_obj.get("status_str") == "error":
                                return None, ErrorDetail(
                                    code="COMFYUI_EXECUTION_FAILED",
                                    message="ComfyUI 任务在生成过程中发生错误",
                                    details={"messages": status_obj.get("messages", [])},
                                    retryable=False,
                                )
            except Exception as e:
                logger.warning(f"Polling history error: {e}")

            await asyncio.sleep(2.0)

        return None, ErrorDetail(
            code="COMFYUI_TIMEOUT",
            message=f"等待 ComfyUI 渲染超时 ({timeout_seconds}秒)",
            retryable=True,
            suggested_action="可在渲染记录中点击重试",
        )

    async def download_output_asset(
        self,
        filename: str,
        subfolder: str,
        asset_type: str,
        dest_path: Path
    ) -> Optional[str]:
        """Download output file from ComfyUI /view or write mock asset."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if self.mock_mode:
            # Create a real playable video / image file using ffmpeg if available
            if dest_path.suffix == ".mp4":
                args = [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-pix_fmt", "yuv420p",
                    str(dest_path), "-loglevel", "error",
                ]
            else:
                args = [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=1",
                    "-frames:v", "1", str(dest_path), "-loglevel", "error",
                ]
            proc = await asyncio.create_subprocess_exec(*args, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("Mock asset generation failed: %s", stderr.decode(errors="replace"))
                return None
            return self._sha256(dest_path)

        # Real download
        try:
            params = {"filename": filename, "subfolder": subfolder, "type": asset_type}
            temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
            hasher = hashlib.sha256()
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                async with client.stream("GET", f"{self.base_url}/view", params=params) as resp:
                    resp.raise_for_status()
                    with temp_path.open("wb") as output:
                        async for chunk in resp.aiter_bytes():
                            output.write(chunk)
                            hasher.update(chunk)
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise RuntimeError("ComfyUI returned an empty asset")
            temp_path.replace(dest_path)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Failed to download asset {filename}: {e}")
            temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
            temp_path.unlink(missing_ok=True)
            return None

    @staticmethod
    def first_video_output(history: dict[str, Any]) -> Optional[dict[str, str]]:
        """Return the first real video emitted by a ComfyUI output node."""
        for node_output in history.get("outputs", {}).values():
            for key in ("videos", "gifs"):
                for asset in node_output.get(key, []):
                    if asset.get("filename"):
                        return {
                            "filename": str(asset["filename"]),
                            "subfolder": str(asset.get("subfolder", "")),
                            "type": str(asset.get("type", "output")),
                        }
        return None

    @staticmethod
    def _sha256(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

comfyui_client = ComfyUIClient()
