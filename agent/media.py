"""Validated project assets, editable sound/subtitle timeline and atomic editing."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Literal
import uuid

from pydantic import Field, model_validator
from agent.models import StrictBaseModel
from agent.execution import exclusive, lease_context
from server.config import settings


def digest(path: Path) -> str:
    with path.open("rb") as source:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
        return hasher.hexdigest()


async def command(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except BaseException as exc:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if isinstance(exc, asyncio.TimeoutError):
            raise ValueError("媒体处理超时（300秒）") from exc
        raise
    if proc.returncode:
        raise ValueError(f"媒体处理失败: {stderr.decode(errors='replace')[-1500:]}")
    return stdout


async def probe(path: Path, decode: bool = True) -> dict:
    data = json.loads(await command("ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)))
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("素材没有可识别的音视频流")
    if decode:
        await command("ffmpeg", "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe", "-i", str(path), "-f", "null", "-")
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("素材时长无效")
    return {"duration": duration, "streams": streams}


class AssetMetadata(StrictBaseModel):
    project_default: bool = False
    purpose: Literal["reference", "voice", "music", "effect"]
    source: str = Field(min_length=1, max_length=2000)
    license_note: str = Field(default="", max_length=2000)
    rights: Literal["pending", "confirmed"] = "pending"
    character_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    shot_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def rights_note(self):
        if self.project_default and self.purpose != "reference":
            raise ValueError("全片默认素材必须是参考图")
        if self.rights == "confirmed" and not self.license_note.strip():
            raise ValueError("确认授权需要填写依据")
        return self


class AudioClip(StrictBaseModel):
    asset_id: str
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    offset: float = Field(default=0, ge=0, allow_inf_nan=False)
    volume: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)
    role: Literal["voice", "music", "effect"]


class Subtitle(StrictBaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=2000)


class Timeline(StrictBaseModel):
    audio: list[AudioClip] = Field(default_factory=list, max_length=100)
    subtitles: list[Subtitle] = Field(default_factory=list, max_length=300)


def srt_time(value: float) -> str:
    ms = round(value * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


class MediaProduction:
    def assets(self, project_id: str) -> list[dict]:
        art = self.db.get_latest_artifact(project_id, "assets")
        return art["content"] if art else []

    def asset_file(self, project_id: str, asset_id: str) -> Path:
        asset = next((a for a in self.assets(project_id) if a["id"] == asset_id), None)
        if not asset:
            raise ValueError(f"素材不存在: {asset_id}")
        path = self._project_file(project_id, asset["file_path"])
        if not path.is_file() or digest(path) != asset["sha256"]:
            raise ValueError(f"素材缺失或已改变: {asset_id}")
        return path

    @exclusive
    async def register_asset(self, project_id: str, data: bytes, metadata: AssetMetadata) -> dict:
        if not self.db.get_project(project_id):
            raise ValueError("Project not found")
        if not 0 < len(data) <= 50 * 1024 * 1024:
            raise ValueError("素材大小必须在 1 字节至 50MB 之间")
        image_header = data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
        audio_header = data.startswith((b"RIFF", b"fLaC", b"OggS", b"ID3", b"\x1aE\xdf\xa3")) or data[4:8] == b"ftyp" or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)
        if not (image_header if metadata.purpose == "reference" else audio_header):
            raise ValueError("文件头不是支持的图片或音频格式")
        screenplay = self.get_screenplay(project_id) or {"project_bible": {"characters": []}, "scenes": []}
        for selected, known in (
            (metadata.character_ids, {c["character_id"] for c in screenplay["project_bible"]["characters"]}),
            (metadata.scene_ids, {s["scene_id"] for s in screenplay["scenes"]}),
            (metadata.shot_ids, {s["shot_id"] for s in self.get_shots(project_id)}),
        ):
            if set(selected) - known:
                raise ValueError("素材关联了不存在的人物、场景或镜头")
        asset_id = "asset_" + uuid.uuid4().hex[:12]
        folder = settings.data_dir / project_id / "assets"
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / (asset_id + ".upload")
        temp.write_bytes(data)
        try:
            info = await probe(temp, decode=False)
            if info["duration"] > 600 or any(s.get("width", 0) * s.get("height", 0) > 24_000_000 for s in info["streams"]):
                raise ValueError("素材超过 10 分钟或 2400 万像素限制")
            codecs = {s.get("codec_name") for s in info["streams"]}
            if metadata.purpose == "reference":
                if not codecs <= {"png", "mjpeg"} or not codecs:
                    raise ValueError("参考图仅支持真实 PNG 或 JPEG 文件")
                await probe(temp)
                ext = ".png" if "png" in codecs else ".jpg"
            else:
                if not any(s.get("codec_type") == "audio" for s in info["streams"]) or info["duration"] <= 0:
                    raise ValueError("声音素材需要有效音轨")
                ext = ".mka"
                converted = folder / (asset_id + ext)
                await command("ffmpeg", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(temp), "-vn", "-c:a", "flac", str(converted))
                temp.unlink()
                temp = converted
            target = folder / (asset_id + ext)
            self.db.assert_lease(project_id, lease_context.get()[2])
            temp.replace(target)
            asset = {"id": asset_id, **metadata.model_dump(), "file_path": str(target), "sha256": digest(target), "media": info}
            assets = self.assets(project_id)
            if metadata.project_default:
                assets = [{**a, "project_default": False} for a in assets]
            self.db.save_artifact(project_id, "assets", [*assets, asset])
            if metadata.project_default:
                self.db.invalidate_artifacts(project_id, ["prompt_package", "workflow_plan", "rough_cut", "comparison_frames"])
            return asset
        finally:
            if temp.suffix == ".upload":
                temp.unlink(missing_ok=True)

    @exclusive
    def update_asset_rights(self, project_id: str, asset_id: str, rights: str, note: str):
        assets = self.assets(project_id)
        asset = next((a for a in assets if a["id"] == asset_id), None)
        if not asset:
            raise ValueError("素材不存在")
        if rights not in ("pending", "confirmed") or (rights == "confirmed" and not note.strip()):
            raise ValueError("确认授权需要填写依据")
        asset.update(rights=rights, license_note=note)
        self.db.save_artifact(project_id, "assets", assets)
        return asset

    def timeline(self, project_id: str) -> dict:
        artifact = self.db.get_latest_artifact(project_id, "timeline")
        if artifact:
            data = artifact["content"]
        else:
            subs, cursor = [], 0.0
            for shot in self.get_shots(project_id):
                text = "\n".join(filter(None, [shot.get("dialogue"), shot.get("voiceover")]))
                if text:
                    subs.append({"start": cursor, "end": cursor + shot["duration_seconds"], "text": text})
                cursor += shot["duration_seconds"]
            data = {"audio": [], "subtitles": subs}
        missing = []
        cursor = 0.0
        for shot in self.get_shots(project_id):
            end = cursor + shot["duration_seconds"]
            if (shot.get("dialogue") or shot.get("voiceover")) and not any(c["role"] == "voice" and c["start"] <= cursor and c["end"] >= end for c in data["audio"]):
                missing.append(shot["shot_id"])
            cursor = end
        return {**data, "missing_voice_shots": missing}

    @exclusive
    def save_timeline(self, project_id: str, timeline: Timeline) -> dict:
        duration = sum(s["duration_seconds"] for s in self.get_shots(project_id))
        assets = {a["id"]: a for a in self.assets(project_id)}
        for clip in [*timeline.audio, *timeline.subtitles]:
            if clip.end <= clip.start or clip.end > duration + 0.001:
                raise ValueError("时间线片段超出成片范围或起止时间无效")
        for clip in timeline.audio:
            self.asset_file(project_id, clip.asset_id)
            asset = assets[clip.asset_id]
            if asset["purpose"] != clip.role or clip.offset + clip.end - clip.start > asset["media"]["duration"] + 0.001:
                raise ValueError("音频用途不符或可用时长不足")
        self.db.save_artifact(project_id, "timeline", timeline.model_dump())
        self.db.invalidate_artifacts(project_id, ["rough_cut"])
        return self.timeline(project_id)

    @exclusive
    async def comparison_frames(self, project_id: str) -> list[dict]:
        result = []
        folder = settings.data_dir / project_id / "outputs"
        for shot in self.get_shots(project_id):
            run = self.db.get_latest_successful_render(project_id, shot["shot_id"])
            if not run or not run.get("output_json"):
                continue
            path = self._project_file(project_id, run["output_json"]["file_path"])
            if not path.is_file() or digest(path) != run["output_json"].get("sha256"):
                raise ValueError("镜头文件已改变，请重新生成")
            info = await probe(path)
            frames = []
            for index, t in enumerate((0, info["duration"] / 2, max(0, info["duration"] - 0.1))):
                name = f"{shot['shot_id']}_{run['id']}_{index}.jpg"
                await command("ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", str(folder / name))
                frames.append(name)
            result.append({"shot_id": shot["shot_id"], "run_id": run["id"], "character_ids": shot["subject_ids"], "location_id": shot["location_id"], "frames": frames})
        self.db.save_artifact(project_id, "comparison_frames", result)
        return result

    @exclusive
    def flag_shot(self, project_id: str, shot_id: str, note: str) -> dict:
        if shot_id not in {s["shot_id"] for s in self.get_shots(project_id)} or not note.strip():
            raise ValueError("需要有效镜头及问题描述")
        result = {"shot_id": shot_id, "note": note[:2000], "role": "human"}
        self.db.save_artifact(project_id, "visual_feedback", result)
        return result

    @exclusive
    async def create_rough_cut(self, project_id: str) -> str:
        self.validate_shots(project_id)
        shots = self.get_shots(project_id)
        timeline_data = self.timeline(project_id)
        timeline = Timeline(audio=timeline_data["audio"], subtitles=timeline_data["subtitles"])
        # Revalidate a saved timeline after a shot edit before any FFmpeg work.
        duration = sum(s["duration_seconds"] for s in shots)
        if any(c.end <= c.start or c.end > duration + .001 for c in [*timeline.audio, *timeline.subtitles]):
            raise ValueError("时间线需要根据当前镜头重新调整")
        out = settings.data_dir / project_id / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        job = out / ("edit_" + uuid.uuid4().hex[:10])
        job.mkdir()
        try:
            current = {p["shot_id"]: p for p in self.get_packages(project_id)["prompt_packages"]}
            packages = self.get_packages(project_id)
            if not current or any(s["shot_id"] not in current for s in shots):
                raise ValueError("请先编译当前镜头的生成包")
            dimensions = next(iter(current.values()))
            width, height, fps = dimensions["width"], dimensions["height"], 24
            files, used_refs = [], set()
            cumulative_duration, previous_frame = 0.0, 0
            for index, shot in enumerate(shots):
                sid = shot["shot_id"]
                run = self.db.get_latest_successful_render(project_id, sid)
                plan = next((p for p in packages["workflow_plans"] if p["shot_id"] == sid), None)
                fingerprint = self.render_fingerprint(project_id, current[sid], plan) if plan and plan.get("status") == "matched" and plan.get("patched_workflow_path") else None
                if not run or run["request_json"].get("fingerprint") != fingerprint:
                    raise ValueError(f"Cannot create rough cut; missing current renders: {sid}")
                path = self._project_file(project_id, run["output_json"]["file_path"])
                if digest(path) != run["output_json"]["sha256"]:
                    raise ValueError(f"镜头文件哈希不符: {sid}")
                info = await probe(path)
                if not any(s["codec_type"] == "video" for s in info["streams"]) or info["duration"] + 2 / fps < shot["duration_seconds"]:
                    raise ValueError(f"镜头实际时长不足: {sid}")
                used_refs.update(current[sid].get("reference_asset_ids", []))
                dest = job / f"shot_{index}.mp4"
                cumulative_duration += shot["duration_seconds"]
                last_frame = round(cumulative_duration * fps)
                frame_count = last_frame - previous_frame
                previous_frame = last_frame
                await command("ffmpeg", "-v", "error", "-y", "-i", str(path), "-frames:v", str(frame_count), "-an", "-vf",
                              f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1,tpad=stop_mode=clone:stop_duration={2/fps}",
                              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest))
                files.append(dest)
            listing = job / "concat.txt"
            listing.write_text("".join(f"file '{p.name}'\n" for p in files))
            joined = job / "joined.mp4"
            await command("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined))
            srt = job / "subtitles.srt"
            srt.write_text("\n\n".join(f"{i+1}\n{srt_time(s.start)} --> {srt_time(s.end)}\n{s.text}" for i, s in enumerate(timeline.subtitles)), encoding="utf-8")
            args = ["ffmpeg", "-v", "error", "-y", "-i", str(joined)]
            filters, labels = [], []
            voice_intervals = [c for c in timeline.audio if c.role == "voice"]
            for i, clip in enumerate(timeline.audio, 1):
                asset_path = self.asset_file(project_id, clip.asset_id)
                info = await probe(asset_path, decode=False)
                if clip.offset + clip.end - clip.start > info["duration"] + .001:
                    raise ValueError("音频可用时长不足")
                args += ["-i", str(asset_path)]
                delay = round(clip.start * 1000)
                filt = f"[{i}:a]atrim=start={clip.offset}:duration={clip.end-clip.start},asetpts=PTS-STARTPTS,volume={clip.volume},adelay={delay}|{delay}"
                if clip.role == "music" and voice_intervals:
                    active = "+".join(f"between(t,{c.start},{c.end})" for c in voice_intervals)
                    filt += f",volume='if(gt({active},0),0.25,1)':eval=frame"
                filters.append(filt + f"[a{i}]")
                labels.append(f"[a{i}]")
            if timeline.subtitles:
                args += ["-i", str(srt)]
            if labels:
                filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad,atrim=duration={duration},loudnorm=I=-16:TP=-1.5:LRA=11[aout]")
                args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]", "-c:a", "aac"]
            else:
                args += ["-map", "0:v", "-an"]
            if timeline.subtitles:
                sub_index = 1 + len(timeline.audio)
                args += ["-map", f"{sub_index}:s:0", "-c:s", "mov_text"]
            candidate = job / "rough_cut.mp4"
            args += ["-c:v", "copy", "-t", str(duration), "-movflags", "+faststart", str(candidate)]
            await command(*args)
            info = await probe(candidate)
            target_duration = self.constraints(project_id)["values"].get("duration_seconds", duration)
            if abs(info["duration"] - target_duration) > max(2/fps, .1):
                raise ValueError("成片时长不符合时间线")
            self.db.assert_lease(project_id, lease_context.get()[2])
            final = out / f"rough_cut_{job.name}.mp4"
            candidate.replace(final)
            used = used_refs | {c.asset_id for c in timeline.audio}
            self.db.save_artifact(project_id, "rough_cut", {"file_path": str(final), "sha256": digest(final), "media": info,
                                  "used_asset_ids": sorted(used), "missing_voice_shots": timeline_data["missing_voice_shots"],
                                  "simulation": settings.llm_mock_mode or (settings.render_backend == "comfyui" and self.comfyui.mock_mode)}, status="confirmed")
            self.db.update_project_status(project_id, "completed")
            return str(final)
        finally:
            import shutil
            shutil.rmtree(job, ignore_errors=True)
