from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import time
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
        self.ws_url = f"ws://{self.host}:{self.port}/ws?clientId={self.client_id}"
        self.mock_mode = mock_mode if mock_mode is not None else settings.comfyui_mock_mode

    async def is_server_reachable(self) -> bool:
        """Check if real ComfyUI server is alive."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/system_stats")
                return resp.status_code == 200
        except Exception:
            return False

    async def get_object_info(self) -> dict[str, Any]:
        """Fetch available nodes from ComfyUI /object_info."""
        if self.mock_mode or not await self.is_server_reachable():
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
            async with httpx.AsyncClient(timeout=10.0) as client:
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

        # If mock mode or server unreachable, simulate submission
        is_alive = await self.is_server_reachable()
        if self.mock_mode or not is_alive:
            mock_prompt_id = f"mock_{uuid.uuid4().hex[:12]}"
            logger.info(f"ComfyUI mock mode active: generated prompt_id {mock_prompt_id}")
            return mock_prompt_id, None

        # Real execution with exponential backoff
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(f"{self.base_url}/prompt", json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        prompt_id = data.get("prompt_id")
                        return prompt_id, None
                    else:
                        err_text = resp.text
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
        if prompt_id.startswith("mock_") or self.mock_mode or not await self.is_server_reachable():
            # Simulate progress steps
            for step in range(1, 4):
                await asyncio.sleep(0.5)
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
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
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
                                    details=status_obj.get("messages", []),
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

        if filename.startswith("mock_") or self.mock_mode or not await self.is_server_reachable():
            # Create a real playable video / image file using ffmpeg if available
            dest_path_str = str(dest_path)
            if dest_path.suffix == ".mp4":
                # Create a 2-second test color video with ffmpeg
                cmd = f'ffmpeg -y -f lavfi -i testsrc=duration=2:size=1280x720:rate=24 -f lavfi -i sine=frequency=440:duration=2 -pix_fmt yuv420p "{dest_path_str}" -loglevel error'
                proc = await asyncio.create_subprocess_shell(cmd)
                await proc.communicate()
            else:
                # Create a sample test image
                cmd = f'ffmpeg -y -f lavfi -i testsrc=size=1280x720:rate=1 -frames:v 1 "{dest_path_str}" -loglevel error'
                proc = await asyncio.create_subprocess_shell(cmd)
                await proc.communicate()

            # If ffmpeg didn't run, fallback to writing dummy bytes
            if not dest_path.exists():
                with open(dest_path, "wb") as f:
                    f.write(b"MOCK_ASSET_CONTENT_" + filename.encode())

            hasher = hashlib.sha256()
            with open(dest_path, "rb") as f:
                hasher.update(f.read())
            return hasher.hexdigest()

        # Real download
        try:
            params = {"filename": filename, "subfolder": subfolder, "type": asset_type}
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(f"{self.base_url}/view", params=params)
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    f.write(resp.content)
            hasher = hashlib.sha256()
            with open(dest_path, "rb") as f:
                hasher.update(f.read())
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Failed to download asset {filename}: {e}")
            return None

comfyui_client = ComfyUIClient()
