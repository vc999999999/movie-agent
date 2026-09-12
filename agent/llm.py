from __future__ import annotations
from pathlib import Path

import json
import logging
import math
import re
from typing import Any, Literal, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

from server.config import settings
from agent.models import (
    AuteurContext,
    BriefExtraction,
    CharacterBible,
    CreativeBrief,
    DialogueLine,
    FilmProductionPack,
    LocationBible,
    ProjectBible,
    SceneSpec,
    ScreenplayPackage,
    ShotSpec,
    TreatmentOption,
    TreatmentPackage,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

def extract_json_block(text: str) -> str:
    """Extract JSON block from markdown code fences or find outermost { } / [ ]."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    # Fallback to finding first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]
    return text

def coerce_to_schema(schema_cls: Type[T], data: Any) -> Any:
    """递归归一化 LLM 输出，使其满足 pydantic schema：

    - 缺失字段：若模型定义了默认值则自动补齐（如 SceneSpec.time_of_day）
    - 列表字段收到字符串：按分隔符拆分或包成单元素列表（如 genre="Neo-Noir" → ["Neo-Noir"]）
    - Literal 枚举字段收到脏值：同义词/中英文映射到合法值，映射不到取最接近的合法值
      （如 shot_size="全景"→"WS"，production_risk="高风险"→"high"）
    - 多余字段：丢弃（配合 extra="forbid"）
    """
    if not isinstance(schema_cls, type) or not issubclass(schema_cls, BaseModel):
        return data
    if not isinstance(data, dict):
        return data

    fields = schema_cls.model_fields
    cleaned: dict[str, Any] = {}
    for name, field_info in fields.items():
        if name not in data or data[name] is None:
            # 缺字段：有默认值就留给 pydantic 填充，必填字段仍然报错
            continue
        value = data[name]
        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)
        # Literal 枚举脏值映射
        if origin is Literal and isinstance(value, str):
            allowed = annotation.__args__
            if value not in allowed:
                value = _map_enum_value(value, allowed)
        # 数字字段收到 "45秒" / "4.5" 等字符串 → 抽取数字
        elif origin is None and annotation in (int, float) and isinstance(value, str):
            m = re.search(r"-?\d+(?:\.\d+)?", value)
            if m:
                value = annotation(m.group(0))
        # list[str] 收到字符串 → 拆分/包裹
        elif origin is list and isinstance(value, str):
            item_type = annotation.__args__[0] if getattr(annotation, "__args__", None) else str
            if item_type is str:
                value = [p.strip() for p in re.split(r"[,，;；、/]", value) if p.strip()] or [value.strip()]
        # 嵌套模型递归
        if origin is None and isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
            value = coerce_to_schema(annotation, value)
        elif origin is list:
            args = getattr(annotation, "__args__", (None,))
            item_type = args[0]
            if isinstance(item_type, type) and issubclass(item_type, BaseModel) and isinstance(value, list):
                value = [coerce_to_schema(item_type, item) if isinstance(item, dict) else item for item in value]
        cleaned[name] = value
    return cleaned


def _map_enum_value(value: str, allowed: tuple) -> Any:
    """把 LLM 的自由文本枚举值映射回合法值；映射不到取第一个合法值兜底。"""
    v = value.strip().lower()
    synonym_table: dict[tuple, dict[str, str]] = {
        # shot_size（景别）
        ("ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"): {
            "ecus": "ECU", "extreme close": "ECU", "大特写": "ECU", "特写镜头": "CU",
            "close": "CU", "特写": "CU", "面部特写": "CU", "近景": "MCU", "中近": "MCU",
            "medium close": "MCU", "中景": "MS", "medium": "MS", "中全景": "MLS", "全景": "WS",
            "medium long": "MLS", "wide": "WS", "远景": "EWS",
            "大远景": "EWS", "extreme wide": "EWS", "establishing": "EWS",
        },
        # production_risk
        ("low", "medium", "high"): {
            "低": "low", "低风险": "low", "高": "high", "高风险": "high", "中": "medium",
            "中风险": "medium", "极低": "low", "极高": "high",
        },
        # generation_mode
        ("text_to_image", "image_to_video", "text_to_video"): {
            "文生图": "text_to_image", "图生视频": "image_to_video", "文生视频": "text_to_video",
            "t2i": "text_to_image", "i2v": "image_to_video", "t2v": "text_to_video",
        },
        # aspect_ratio
        ("16:9", "9:16", "1:1", "2.39:1"): {
            "横屏": "16:9", "竖屏": "9:16", "方形": "1:1", "宽银幕": "2.39:1",
        },
        # dialogue_mode
        ("none", "voiceover", "dialogue", "mixed"): {
            "无对白": "none", "旁白": "voiceover", "画外音": "voiceover",
            "对白": "dialogue", "混合": "mixed",
        },
        # platform
        ("douyin", "bilibili", "youtube", "other"): {
            "抖音": "douyin", "b站": "bilibili", "youtube": "youtube", "其他": "other",
        },
        # purpose
        ("short_film", "trailer", "ad", "music_video", "social_video"): {
            "短片": "short_film", "预告": "trailer", "预告片": "trailer",
            "广告": "ad", "mv": "music_video", "社交": "social_video",
        },
    }
    for allowed_set, table in synonym_table.items():
        if set(allowed_set) == set(allowed):
            # 先精确匹配，再子串匹配（按表序），避免"全景"误命中"中全景"
            if v in table:
                return table[v]
            for hint, target in table.items():
                if hint in v or v in hint:
                    return target
            break
    # 兜底：包含关系匹配（如 "high risk" 含 "high"）
    for candidate in allowed:
        if isinstance(candidate, str) and (candidate.lower() in v or v in candidate.lower()):
            return candidate
    return allowed[0]


class LLMService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.openai_api_key
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.model = model or settings.openai_model

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    async def call_llm(self, system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
        """Raw API call to OpenAI-compatible chat endpoint.

        Streamed by default: some providers (ModelScope API-Inference) return
        an empty body for non-streaming calls, and SSE reassembly works on
        every OpenAI-compatible endpoint.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": True,
        }

        content_parts: list[str] = []
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: "):].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    content_parts.append(choices[0].get("delta", {}).get("content") or "")
        content = "".join(content_parts)
        if not content.strip():
            raise RuntimeError(
                f"LLM streaming returned empty content (model={self.model}, base_url={self.base_url})"
            )
        return content

    async def structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: Type[T],
        fallback_fn: Optional[Any] = None
    ) -> T:
        """Call the LLM with one schema-repair attempt.

        Deterministic demo data is available only when explicitly enabled. Production
        requests must fail visibly instead of being replaced by fabricated output.
        """
        if not self.has_api_key:
            if settings.llm_mock_mode and fallback_fn:
                return fallback_fn()
            raise RuntimeError("OPENAI_API_KEY is not set (set LLM_MOCK_MODE=true only for local demos/tests)")

        # Send the actual schema; naming a Python model is insufficient for the LLM.
        system_prompt += (
            "\n\nRequired JSON Schema (include all required fields exactly as named):\n"
            + json.dumps(schema_cls.model_json_schema(), ensure_ascii=False)
        )

        # First attempt
        content = await self.call_llm(system_prompt, user_prompt)
        raw_json = extract_json_block(content)

        try:
            parsed = json.loads(raw_json)
            return schema_cls.model_validate(coerce_to_schema(schema_cls, parsed))
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Initial LLM response validation failed: {e}. Attempting 1 repair call...")

            # Repair call
            repair_prompt = (
                f"Your previous output failed JSON validation or schema check:\nError: {e}\n\n"
                f"Original task and constraints:\n{user_prompt}\n\n"
                f"Previous output:\n{content}\n\n"
                f"Please fix and output ONLY the valid JSON object conforming to the required schema."
            )
            try:
                repair_content = await self.call_llm(system_prompt, repair_prompt)
                repair_json = extract_json_block(repair_content)
                parsed = json.loads(repair_json)
                return schema_cls.model_validate(coerce_to_schema(schema_cls, parsed))
            except Exception as repair_err:
                logger.error(f"Repair call also failed: {repair_err}")
                if settings.llm_mock_mode and fallback_fn:
                    logger.info("Using fallback generator after repair failure.")
                    return fallback_fn()
                raise

    # 7.1 Call A: Extract Brief
    async def extract_brief(
        self,
        user_text: str,
        previous_brief: Optional[dict[str, Any]] = None,
        answers: Optional[list[dict[str, str]]] = None,
    ) -> BriefExtraction:
        system_prompt = Path(settings.prompts_dir / "extract_brief.md").read_text(encoding="utf-8")
        user_prompt = f"User input:\n{user_text}\n\nPrevious brief:\n{json.dumps(previous_brief or {}, ensure_ascii=False)}\n\nNew Answers:\n{json.dumps(answers or [], ensure_ascii=False)}"

        def fallback() -> BriefExtraction:
            # High quality deterministic extraction
            known: dict[str, Any] = {}
            conflicts: list[str] = []
            confidence: dict[str, float] = {}
            assumptions: list[str] = []

            # Basic keyword parsing
            known["logline"] = user_text[:120].strip() if user_text else "精彩电影短片"
            confidence["logline"] = 0.95

            # Duration detection
            dur_match = re.search(r"(\d+)\s*(?:秒|s|sec)", user_text)
            if dur_match:
                d = int(dur_match.group(1))
                known["duration_seconds"] = max(10, min(90, d))
                confidence["duration_seconds"] = 1.0
            else:
                known["duration_seconds"] = 45
                confidence["duration_seconds"] = 0.7
                assumptions.append("未明确指定时长，默认按标准短片 45 秒规划")

            # Aspect ratio
            if "竖屏" in user_text or "9:16" in user_text or "抖音" in user_text:
                known["aspect_ratio"] = "9:16"
                known["platform"] = "douyin"
                confidence["aspect_ratio"] = 1.0
            elif "宽银幕" in user_text or "2.39" in user_text:
                known["aspect_ratio"] = "2.39:1"
                confidence["aspect_ratio"] = 1.0
            else:
                known["aspect_ratio"] = "16:9"
                confidence["aspect_ratio"] = 0.75
                assumptions.append("未指定画幅，默认采用 16:9 横屏")

            # Style & genre
            genres = []
            if "赛博朋克" in user_text:
                genres.append("赛博朋克")
            if "侦探" in user_text or "悬疑" in user_text or "追凶" in user_text:
                genres.append("悬疑")
                genres.append("犯罪")
            if "科幻" in user_text:
                genres.append("科幻")
            known["genre"] = genres or ["剧情", "悬疑"]

            if "赛博朋克" in user_text or "雨夜" in user_text:
                known["visual_style"] = "赛博朋克雨夜写实电影感，霓虹倒影，冷暖高对比度调色，35mm胶片质感"
                confidence["visual_style"] = 0.85
            else:
                known["visual_style"] = "写实电影质感，自然环境光，电影级色彩调校"
                confidence["visual_style"] = 0.75

            # Protagonist & goal
            if "侦探" in user_text:
                known["protagonist"] = "沉着冷酷的私家侦探"
                known["protagonist_goal"] = "在阴谋与暴风雨笼罩的城市中追缉危险凶手"
                known["conflict"] = "狡猾的嫌疑人不断设下致命伏击，试图消灭所有目击证人"
            else:
                known["protagonist"] = "核心主人公"
                known["protagonist_goal"] = "突破重围达成目标"
                known["conflict"] = "强敌与险恶环境的双重压迫"

            # Apply user answers
            if answers:
                for ans in answers:
                    field = ans.get("field")
                    val = ans.get("answer", "")
                    if "你决定" in val or "随便" in val or "默认" in val:
                        assumptions.append(f"用户对于 '{field}' 选择 Agent 推荐默认配置")
                        continue

                    if field == "duration_seconds":
                        m = re.search(r"(\d+)", val)
                        if m:
                            known["duration_seconds"] = int(m.group(1))
                            confidence["duration_seconds"] = 1.0
                    elif field == "aspect_ratio":
                        if "竖屏" in val or "9:16" in val:
                            known["aspect_ratio"] = "9:16"
                        elif "2.39" in val or "宽银幕" in val:
                            known["aspect_ratio"] = "2.39:1"
                        elif "1:1" in val:
                            known["aspect_ratio"] = "1:1"
                        else:
                            known["aspect_ratio"] = "16:9"
                        confidence["aspect_ratio"] = 1.0
                    elif field == "ending":
                        known["ending"] = val
                        confidence["ending"] = 1.0
                    elif field == "dialogue_mode":
                        if "无对白" in val:
                            known["dialogue_mode"] = "none"
                        elif "角色对白" in val:
                            known["dialogue_mode"] = "dialogue"
                        elif "混合" in val:
                            known["dialogue_mode"] = "mixed"
                        else:
                            known["dialogue_mode"] = "voiceover"
                        confidence["dialogue_mode"] = 1.0
                    elif field in ["visual_style", "protagonist", "protagonist_goal", "conflict"]:
                        known[field] = val
                        confidence[field] = 1.0

            return BriefExtraction(
                known=known,
                conflicts=conflicts,
                confidence=confidence,
                assumptions=assumptions,
            )

        return await self.structured_call(system_prompt, user_prompt, BriefExtraction, fallback_fn=fallback)

    async def generate_treatments(
        self,
        brief: CreativeBrief,
        packs: list[FilmProductionPack],
        auteur: Optional[AuteurContext] = None,
    ) -> TreatmentPackage:
        system_prompt = Path(settings.prompts_dir / "generate_treatments.md").read_text(encoding="utf-8")
        user_prompt = (
            f"Creative Brief:\n{brief.model_dump_json(indent=2)}\n\n"
            f"Available Production Packs:\n{json.dumps([p.model_dump() for p in packs], ensure_ascii=False, indent=2)}"
        )
        if auteur:
            user_prompt += f"\n\nSelected Auteur Technique Context:\n{auteur.model_dump_json(indent=2)}"

        def fallback() -> TreatmentPackage:
            variant = next(
                (item for item in auteur.profile.variants if item.variant_id == auteur.selection.variant_id),
                None,
            ) if auteur else None
            options = [
                TreatmentOption(
                    treatment_id=f"treatment_{index:02d}",
                    name=pack.name,
                    core_question=brief.conflict or f"{brief.protagonist or '主角'}能否完成目标？",
                    logline=brief.logline,
                    structure="；".join(beat.purpose for beat in pack.narrative_pattern.beats),
                    visual_strategy="；".join(filter(None, [
                        pack.directing_grammar.intent,
                        f"采用{variant.name}：{variant.techniques[0].instruction}" if variant else "",
                    ])),
                    production_pack_id=pack.pack_id,
                    production_risk="high" if "action" in pack.pack_id else "medium",
                    estimated_shots=max(3, min(30, math.ceil(brief.duration_seconds / pack.generation_recipe.max_duration_seconds))),
                    technique_plan=[technique.technique_id for technique in variant.techniques] if variant else [],
                    viewer_effect="；".join(technique.viewer_effect for technique in variant.techniques) if variant else "",
                )
                for index, pack in enumerate(packs[:3], start=1)
            ]
            return TreatmentPackage(
                options=options,
                recommendation=options[0].treatment_id,
                recommendation_reason="首选方案与用户类型和关键词最匹配，并在当前工作流单镜头时长限制内可稳定拆解。",
            )

        return await self.structured_call(
            system_prompt,
            user_prompt,
            TreatmentPackage,
            fallback_fn=fallback,
        )

    # 7.2 Call B: Build Screenplay
    async def build_screenplay(
        self,
        brief: CreativeBrief,
        treatment: Optional[TreatmentOption] = None,
        auteur: Optional[AuteurContext] = None,
    ) -> ScreenplayPackage:
        system_prompt = Path(settings.prompts_dir / "build_screenplay.md").read_text(encoding="utf-8")
        user_prompt = f"Creative Brief:\n{brief.model_dump_json(indent=2)}"
        if treatment:
            user_prompt += f"\n\nConfirmed Treatment:\n{treatment.model_dump_json(indent=2)}"
        if auteur:
            user_prompt += f"\n\nSelected Auteur Technique Context:\n{auteur.model_dump_json(indent=2)}"

        def fallback() -> ScreenplayPackage:
            # Deterministic screenplay matching brief duration and themes
            char_id = "char_protagonist_01"
            loc_id = "loc_city_alley_01"

            char = CharacterBible(
                character_id=char_id,
                name=brief.protagonist or "主角",
                narrative_role="Protagonist",
                age_range="30-35",
                gender_presentation="Male",
                fixed_appearance="深邃坚毅的眼神，留着稀疏胡茬，黑发在雨水中被打湿贴在额头",
                fixed_costume="穿着经典深灰防水风衣，立起衣领，内搭黑色高领毛衣与战术皮靴",
                personality=["敏锐", "警惕", "孤勇"],
                voice="低沉沙哑且充满压迫感的磁性嗓音",
                reference_asset_ids=[],
                forbidden_changes=["面容轮廓", "风衣款式与颜色", "发型结构"],
            )

            loc = LocationBible(
                location_id=loc_id,
                name="雨夜窄巷与霓虹废墟",
                fixed_visual_description="潮湿反光的湿漉青石路面，两侧斑驳旧砖墙贴满破旧海报，头顶错落交织的电线与泛着幽蓝光芒的霓虹招牌在雨水中闪烁",
                layout_notes="狭长巷道，尽头有铁丝网与蒸汽管道",
                time_of_day="深夜暴雨",
                weather="强暴雨，伴随升腾的地面水汽",
                lighting_baseline="雨水倒影中的冷调幽蓝与品红霓虹高光，局部阴影浓重",
                reference_asset_ids=[],
                forbidden_changes=["建筑结构", "湿漉反射材质", "冷暖环境主光源"],
            )

            bible = ProjectBible(
                title=brief.title or "雨夜追缉",
                logline=brief.logline,
                genre=brief.genre,
                visual_style=brief.visual_style,
                aspect_ratio=brief.aspect_ratio,
                target_duration=brief.duration_seconds,
                characters=[char],
                locations=[loc],
                global_negative_prompt="cartoon, 3d render, anime, worst quality, low quality, oversaturated, blurry",
                color_palette=["#0A0F1D", "#1A3B5C", "#00F0FF", "#FF0055", "#8E9AA8"],
                soundtrack_style="低沉心跳脉冲电子合成器，伴随急促雨声与雷鸣",
            )

            # Scene 1
            scene1 = SceneSpec(
                scene_id="scene_01",
                order=1,
                heading="EXT. 霓虹暗巷 - 深夜暴雨",
                location_id=loc_id,
                time_of_day="深夜暴雨",
                estimated_duration=float(brief.duration_seconds),
                purpose="建立紧张压抑的追凶氛围，展现主角迫近目标并直面危险对抗",
                characters=[char_id],
                setup="暴雨如注的街巷，霓虹灯倒映在泥泞水洼中微微晃动",
                action_beats=[
                    "主角疾步穿梭于湿漉的小巷中，警惕观察四周可疑痕迹",
                    "在巷道拐角处发现被遗弃的带血证物，立即拔枪警戒",
                    "前方暗影中一道模糊身影掠过，主角冒雨全力追击，画面定格在悬疑关头",
                ],
                dialogue=[
                    DialogueLine(character_id=char_id, text="雨夜会洗刷很多罪恶，但洗不掉猎手的脚步。", emotion="低沉冷峻")
                ] if brief.dialogue_mode in ["voiceover", "mixed", "dialogue"] else [],
                transition_in="FADE_IN",
                transition_out="FADE_OUT",
                continuity_in=["雨夜湿地反射环境"],
                continuity_out=["人物雨衣湿透状态保持"],
            )

            return ScreenplayPackage(project_bible=bible, scenes=[scene1])

        return await self.structured_call(system_prompt, user_prompt, ScreenplayPackage, fallback_fn=fallback)

    # 7.3 Call C: Build Shot List
    async def build_shot_list(
        self,
        screenplay_pkg: ScreenplayPackage,
        brief: CreativeBrief,
        pack: Optional[FilmProductionPack] = None,
        auteur: Optional[AuteurContext] = None,
    ) -> list[ShotSpec]:
        system_prompt = Path(settings.prompts_dir / "build_shots.md").read_text(encoding="utf-8")
        user_prompt = (
            f"Screenplay Package:\n{screenplay_pkg.model_dump_json(indent=2)}\n\n"
            f"Target Duration: {brief.duration_seconds} seconds"
        )
        if pack:
            user_prompt += f"\n\nRequired Production Pack:\n{pack.model_dump_json(indent=2)}"
        if auteur:
            user_prompt += f"\n\nSelected Auteur Technique Context:\n{auteur.model_dump_json(indent=2)}"

        # Timing is a production constraint, not an LLM arithmetic task.
        max_duration = min(12.0, pack.generation_recipe.max_duration_seconds if pack else 8.0)
        shot_count = max(3, math.ceil(brief.duration_seconds / min(4.5, max_duration)))
        total_ms = brief.duration_seconds * 1000
        base_ms, remainder = divmod(total_ms, shot_count)
        durations = [(base_ms + (1 if i < remainder else 0)) / 1000 for i in range(shot_count)]
        timing_prompt = (
            f"\n\nMandatory shot timing plan: exactly {shot_count} shots, in order. "
            f"duration_seconds for each shot: {json.dumps(durations)}. "
            f"Total: {brief.duration_seconds}s; maximum per shot: {max_duration}s. "
            "Design the action to fit each assigned slot. Do not omit, merge, or add slots. "
            "This timing plan overrides generic duration advice."
        )
        user_prompt += f"\n\nComplete Creative Brief:\n{brief.model_dump_json(indent=2)}" + timing_prompt
        if pack:
            user_prompt += (
                f"\nEvery grammar_pack_id must be {pack.pack_id!r} (the pack_id, not grammar_id). "
                "sequence_pattern is a key from directing_grammar.sequence_patterns; "
                "shot_function must be one of the values belonging to that key. "
                "For the selected first-frame I2V workflow, set first_frame_required=true "
                "and last_frame_required=false; end_frame describes the intended ending, not a required input image."
            )

        class ShotListWrapper(BaseModel):
            shots: list[ShotSpec]

        def fallback() -> list[ShotSpec]:
            total_dur = brief.duration_seconds
            # For 45s: 3 ~ 4 shots; e.g. 3 shots of 15s or 8 shots of ~5.5s
            # Plan shots with duration 3.0 ~ 5.5s each, matching total_dur strictly within 5%!
            # Target count:
            max_duration = pack.generation_recipe.max_duration_seconds if pack else 8.0
            shot_count = max(3, min(30, math.ceil(total_dur / min(4.5, max_duration))))
            dur_per_shot = round(total_dur / shot_count, 1)

            # Ensure sum matches total_dur exactly
            durations = [dur_per_shot] * shot_count
            diff = round(total_dur - sum(durations), 1)
            durations[-1] = round(durations[-1] + diff, 1)

            shots = []
            char_id = screenplay_pkg.project_bible.characters[0].character_id
            loc_id = screenplay_pkg.project_bible.locations[0].location_id
            auteur_variant = next(
                (item for item in auteur.profile.variants if item.variant_id == auteur.selection.variant_id),
                None,
            ) if auteur else None

            shot_templates = [
                {
                    "purpose": "确立环境与危机开端，展现雨夜氛围",
                    "start": "深巷全景，雨水从生锈铁管道倾泻而下，霓虹倒影碎裂在积水中",
                    "action": "主角风衣背影从画面边缘缓步踏入积水，脚下溅起水花，侧身警惕扫视",
                    "end": "主角在幽暗路灯下停住脚步，侧脸显露在冷蓝光线中",
                    "size": "WS", "angle": "低角度俯仰平视", "mov": "缓慢水平推近", "comp": "三分法纵深构图",
                    "light": "深蓝冷夜光配粉红霓虹边缘光", "mood": "神秘压抑", "mode": "image_to_video"
                },
                {
                    "purpose": "发现关键凶案证物，推进叙事悬念",
                    "start": "地面湿漉青石板特写，一处掉落的破碎芯片在微光中闪烁电路红光",
                    "action": "主角蹲下身，皮质手套拾起染有水渍的芯片，镜头随手部动作缓缓升起",
                    "end": "主角将芯片紧握在手心，眼神凌厉望向前方漆黑巷道",
                    "size": "CU", "angle": "平视特写", "mov": "倾斜跟移", "comp": "中心聚焦",
                    "light": "手电筒冷白聚光与环境低照度交织", "mood": "高度警觉", "mode": "image_to_video"
                },
                {
                    "purpose": "锁定目标踪迹，展开雨夜追逐对抗",
                    "start": "主角中近景，大雨顺着风衣帽檐不断滴落，右手拔出腰间配枪",
                    "action": "远处阴影中一道黑袍人影急速掠过，主角毫不犹豫疾步狂奔破开雨帘追赶",
                    "end": "两人身影在蒸汽与飞溅的水雾中一前一后没入狭窄转角",
                    "size": "MS", "angle": "手持跟随微仰", "mov": "高速推轨跟拍", "comp": "动态对角线构图",
                    "light": "破损招牌闪烁电弧产生的频闪硬光", "mood": "狂暴紧张", "mode": "image_to_video"
                },
                {
                    "purpose": "高潮对峙停格，留下悬念预告收束",
                    "start": "巷道死胡同铁丝网前，背对镜头的神秘人骤然回身",
                    "action": "主角举枪对准黑影，暴风雨达到顶点，一道惊雷划破夜空照亮对峙双方",
                    "end": "画面在枪声与雷鸣轰然响起的刹那黑幕定格",
                    "size": "MCU", "angle": "极低仰角戏剧性视角", "mov": "快速推近定格", "comp": "对称双人对峙构图",
                    "light": "闪电瞬间超强冷白过曝硬光转全黑", "mood": "震撼悬疑", "mode": "image_to_video"
                }
            ]

            for i in range(shot_count):
                tmpl = shot_templates[i % len(shot_templates)]
                s_id = f"s01_sh{i+1:02d}"
                dur = durations[i]
                sequence_name = next(iter(pack.directing_grammar.sequence_patterns)) if pack else None
                sequence = pack.directing_grammar.sequence_patterns[sequence_name] if pack and sequence_name else []
                beat = pack.narrative_pattern.beats[i % len(pack.narrative_pattern.beats)] if pack else None
                technique_count = 2 if auteur and auteur.selection.intensity == "strong" else 1
                apply_technique = bool(auteur_variant) and not (
                    auteur.selection.intensity == "subtle" and i % 2
                )
                techniques = [
                    auteur_variant.techniques[(i + offset) % len(auteur_variant.techniques)]
                    for offset in range(technique_count)
                ] if apply_technique and auteur_variant else []
                shots.append(ShotSpec(
                    shot_id=s_id,
                    scene_id="scene_01",
                    order=i + 1,
                    beat_id=f"beat_{beat.role}_{i + 1:02d}" if beat else None,
                    grammar_pack_id=pack.pack_id if pack else None,
                    sequence_pattern=sequence_name,
                    shot_function=sequence[i % len(sequence)] if sequence else None,
                    information_revealed=tmpl["purpose"] if pack else None,
                    information_withheld=brief.ending if pack and i < shot_count - 1 else None,
                    screen_direction="left_to_right" if pack else None,
                    axis_id="axis_scene_01" if pack else None,
                    auteur_profile_id=auteur.profile.profile_id if auteur else None,
                    auteur_variant_id=auteur.selection.variant_id if auteur else None,
                    technique_ids=[technique.technique_id for technique in techniques],
                    technique_rationale="；".join(
                        f"{technique.name}：{technique.instruction}" for technique in techniques
                    ) or None,
                    duration_seconds=dur,
                    narrative_purpose=tmpl["purpose"],
                    subject_ids=[char_id],
                    location_id=loc_id,
                    start_frame=tmpl["start"],
                    action=tmpl["action"],
                    end_frame=tmpl["end"],
                    shot_size=pack.directing_grammar.preferred_sizes[i % len(pack.directing_grammar.preferred_sizes)] if pack else tmpl["size"],
                    camera_angle=tmpl["angle"],
                    camera_movement=pack.directing_grammar.preferred_movements[i % len(pack.directing_grammar.preferred_movements)] if pack else tmpl["mov"],
                    composition=tmpl["comp"],
                    lens="35mm Anamorphic Prime",
                    fps=24,
                    lighting=tmpl["light"],
                    mood=tmpl["mood"],
                    dialogue=None,
                    voiceover="凶手的阴影就在拐角处，而雨还在继续下。" if i == 0 and brief.dialogue_mode in ["voiceover", "mixed"] else None,
                    sound_effects=["暴雨声", "脚步踩水声", "雷鸣"],
                    music_cue="紧张脉冲大提琴起奏" if i == 0 else None,
                    continuity_requirements=["主角风衣湿水质感保持", "环境冷幽蓝调色一致"],
                    reference_asset_ids=[],
                    generation_mode=pack.generation_recipe.generation_mode if pack else tmpl["mode"],
                    first_frame_required=True,
                    last_frame_required=False,
                ))

            return shots

        res = await self.structured_call(system_prompt, user_prompt, ShotListWrapper, fallback_fn=lambda: ShotListWrapper(shots=fallback()))
        if len(res.shots) != shot_count:
            repair_prompt = (
                user_prompt + f"\nPrevious response contained {len(res.shots)} shots instead of {shot_count}. "
                "Replan the action across every assigned slot, preserving the brief and selected treatment.\n"
                + res.model_dump_json()
            )
            res = await self.structured_call(system_prompt, repair_prompt, ShotListWrapper, fallback_fn=lambda: ShotListWrapper(shots=fallback()))
        if len(res.shots) != shot_count:
            raise ValueError(f"分镜需要 {shot_count} 个镜头以满足 {brief.duration_seconds} 秒和单镜头上限，模型修复后仍返回 {len(res.shots)} 个，请重试生成")
        # The model has authored against these slots; persist the exact production timing.
        return [shot.model_copy(update={"duration_seconds": duration}) for shot, duration in zip(res.shots, durations)]

llm_service = LLMService()
