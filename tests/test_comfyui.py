import pytest

from agent.comfyui import ComfyUIClient


def test_first_video_output_uses_history_metadata():
    history = {
        "outputs": {
            "60": {
                "videos": [
                    {"filename": "render.mp4", "subfolder": "shots", "type": "output"}
                ]
            }
        }
    }

    assert ComfyUIClient.first_video_output(history) == {
        "filename": "render.mp4",
        "subfolder": "shots",
        "type": "output",
    }


@pytest.mark.asyncio
async def test_unreachable_server_does_not_fake_success():
    client = ComfyUIClient(host="127.0.0.1", port=1, mock_mode=False)
    prompt_id, error = await client.submit_prompt({}, max_retries=0)

    assert prompt_id is None
    assert error is not None
    assert error.code == "COMFYUI_CONNECTION_ERROR"


def test_native_webm_output_ignores_preview_image():
    history = {"outputs": {"28": {"images": [{"filename": "preview.webp"}]}, "47": {"images": [{"filename": "shot.webm", "subfolder": "", "type": "output"}]}}}
    assert ComfyUIClient.first_video_output(history)["filename"] == "shot.webm"
    assert ComfyUIClient.first_video_output({"outputs": {"28": {"images": [{"filename": "preview.webp"}]}}}) is None
