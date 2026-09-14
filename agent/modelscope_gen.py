"""ModelScope API-Inference generation backend.

Cloud alternative to the ComfyUI backend for GPU-less hosts (e.g. ModelScope
Studio free containers). Implements the official async task protocol:

- Image: POST /v1/images/generations (X-ModelScope-Async-Mode: true)
- Video: POST /v1/videos/generations (X-ModelScope-DataInspection header)
- Poll:  GET /v1/tasks/{task_id} (X-ModelScope-Task-Type: image|video_generation)

The pipeline calls submit_shot() with the same patched PromptPackage payload
that ComfyUI would receive, so the two backends are interchangeable.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional
import uuid

import httpx
from server.config import settings
from agent.models import ErrorDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://api-inference.modelscope.cn"
IMAGE_MODEL = "Qwen/Qwen-Image"
VIDEO_MODEL = "Wan-AI/Wan2.1-T2V-1.3B"
POLL_INTERVAL_SECONDS = 10.0


class ModelScopeGenClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ):
        self.api_key = api_key or settings.modelscope_api_key
        self.poll_interval = poll_interval

    @property
    def available(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1280,
        height: int = 720,
        seed: Optional[int] = None,
        timeout_seconds: int = 600,
    ) -> tuple[Optional[str], Optional[ErrorDetail]]:
        """Text-to-image. Returns the image URL on success."""
        payload: dict[str, Any] = {
            "model": IMAGE_MODEL,
            "prompt": prompt[:2000],
            "size": f"{width}x{height}",
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt[:2000]
        if seed is not None:
            payload["seed"] = seed

        submit_err = await self._submit("images/generations", payload, async_mode=True)
        task_id, submit_err = submit_err
        if submit_err or not task_id:
            return None, submit_err or ErrorDetail(
                code="MS_SUBMIT_FAILED", message="图片任务提交失败", retryable=True,
            )

        result, err = await self._poll(
            task_id, "image_generation", timeout_seconds,
            extract=lambda d: (d.get("output_images") or [None])[0],
        )
        if err:
            return None, err
        return result, None

    async def generate_video(
        self,
        prompt: str,
        negative_prompt: str = "",
        timeout_seconds: int = 1800,
    ) -> tuple[Optional[str], Optional[ErrorDetail]]:
        """Text-to-video via Wan 1.3B. Returns the video URL on success.

        Free-tier video concurrency is 1; a 429 here means the account still
        has a task in the queue, which the caller should retry later.
        """
        payload: dict[str, Any] = {
            "model": VIDEO_MODEL,
            "prompt": prompt[:2000],
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt[:2000]

        submit_err = await self._submit(
            "videos/generations",
            payload,
            async_mode=False,
            extra_headers={"X-ModelScope-DataInspection": '{"input": true, "output": true}'},
        )
        task_id, submit_err = submit_err
        if submit_err or not task_id:
            return None, submit_err or ErrorDetail(
                code="MS_SUBMIT_FAILED", message="视频任务提交失败", retryable=True,
            )

        result, err = await self._poll(
            task_id, "video_generation", timeout_seconds,
            extract=lambda d: (d.get("output_videos") or d.get("output_images") or [None])[0],
        )
        if err:
            return None, err
        return result, None

    async def submit_video(self, prompt: str, negative_prompt: str = ""):
        return await self._submit("videos/generations", {"model": VIDEO_MODEL, "prompt": prompt[:2000], "negative_prompt": negative_prompt[:2000]},
                                  async_mode=False, extra_headers={"X-ModelScope-DataInspection": '{"input": true, "output": true}'})

    async def poll_video(self, task_id: str):
        return await self._poll(task_id, "video_generation", 1800,
                                extract=lambda data: (data.get("output_videos") or [None])[0])

    async def download_asset(self, url: str, dest_path: Path) -> Optional[str]:
        """Download a generated asset to dest_path, return sha256 hex digest."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
        import hashlib
        hasher = hashlib.sha256()
        try:
            async with httpx.AsyncClient(timeout=300.0, trust_env=False) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with temp_path.open("wb") as output:
                        async for chunk in resp.aiter_bytes():
                            output.write(chunk)
                            hasher.update(chunk)
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise RuntimeError("ModelScope returned an empty asset")
            temp_path.replace(dest_path)
            return hasher.hexdigest()
        except Exception as e:
            logger.error(f"Failed to download asset {url}: {e}")
            temp_path.unlink(missing_ok=True)
            return None

    async def _submit(
        self,
        path: str,
        payload: dict[str, Any],
        async_mode: bool,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> tuple[Optional[str], Optional[ErrorDetail]]:
        """Submit an async task. Returns (task_id, error); success has error=None."""
        headers = self._headers()
        if async_mode:
            headers["X-ModelScope-Async-Mode"] = "true"
        if extra_headers:
            headers.update(extra_headers)
        try:
            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                resp = await client.post(f"{BASE_URL}/v1/{path}", headers=headers, json=payload)
                body = resp.json()
                task_id = body.get("task_id")
                if resp.status_code == 200 and task_id:
                    return task_id, None
                # Some providers return 200-without-task or 4xx/5xx bodies
                code = body.get("errors", {}).get("code") or body.get("error", {}).get("code")
                message = str(body.get("errors", {}).get("message") or body.get("error", {}).get("message") or body)[:500]
                retryable = resp.status_code == 429
                return None, ErrorDetail(
                    code=f"MS_SUBMIT_HTTP_{resp.status_code}" if 400 <= resp.status_code < 500 else "SUBMISSION_UNCERTAIN",
                    message=message or f"ModelScope HTTP {resp.status_code}",
                    details={"body": message},
                    retryable=retryable,
                )
        except (httpx.TimeoutException, httpx.ReadError, ValueError) as e:
            return None, ErrorDetail(code="SUBMISSION_UNCERTAIN", message=str(e))
        except httpx.ConnectError as e:
            return None, ErrorDetail(
                code="MS_CONNECTION_ERROR",
                message=f"无法连接 ModelScope API-Inference: {e}",
                retryable=True,
            )

    async def _poll(
        self,
        task_id: str,
        task_type: str,
        timeout_seconds: int,
        extract,
    ) -> tuple[Optional[str], Optional[ErrorDetail]]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                    resp = await client.get(
                        f"{BASE_URL}/v1/tasks/{task_id}",
                        headers={**self._headers(), "X-ModelScope-Task-Type": task_type},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        status = data.get("task_status")
                        if status == "SUCCEED":
                            result = extract(data)
                            if result:
                                return result, None
                            return None, ErrorDetail(
                                code="MS_OUTPUT_MISSING",
                                message=f"任务成功但未返回输出: {str(data)[:400]}",
                                retryable=False,
                            )
                        if status == "FAILED":
                            return None, ErrorDetail(
                                code="MS_TASK_FAILED",
                                message=f"ModelScope 任务失败: {str(data.get('errors') or data)[:400]}",
                                retryable=False,
                            )
            except Exception as e:
                logger.warning(f"Polling ModelScope task {task_id}: {e}")
            await asyncio.sleep(self.poll_interval)
        return None, ErrorDetail(
            code="MS_TIMEOUT",
            message=f"等待 ModelScope 任务超时 ({timeout_seconds}s): {task_id}",
            retryable=True,
        )


modelscope_gen_client = ModelScopeGenClient()
