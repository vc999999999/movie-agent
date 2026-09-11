from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from agent.models import (
    AuteurContext,
    AuteurProfile,
    AuteurSelection,
    AuteurVariant,
    CreativeBrief,
    FilmProductionPack,
    GrammarIssue,
    ShotSpec,
)
from server.config import settings


class ProductionPackRegistry:
    def __init__(self, packs_dir: Optional[Path] = None):
        self.packs_dir = packs_dir or settings.production_packs_dir
        self.packs: dict[str, FilmProductionPack] = {}
        self.load_all()

    def load_all(self) -> None:
        self.packs.clear()
        if not self.packs_dir.is_dir():
            raise RuntimeError(f"Production pack directory not found: {self.packs_dir}")

        for path in sorted(self.packs_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            pack = FilmProductionPack.model_validate(data)
            if pack.pack_id in self.packs:
                raise ValueError(f"Duplicate production pack ID: {pack.pack_id}")
            if abs(sum(beat.ratio for beat in pack.narrative_pattern.beats) - 1) > 0.001:
                raise ValueError(f"Narrative beat ratios must total 1: {path.name}")
            if pack.narrative_pattern.duration_range[0] > pack.narrative_pattern.duration_range[1]:
                raise ValueError(f"Invalid duration range: {path.name}")
            if not pack.directing_grammar.preferred_sizes or not pack.directing_grammar.preferred_movements:
                raise ValueError(f"Directing vocabulary cannot be empty: {path.name}")
            if not pack.directing_grammar.sequence_patterns or any(
                not functions for functions in pack.directing_grammar.sequence_patterns.values()
            ):
                raise ValueError(f"Sequence patterns cannot be empty: {path.name}")
            self.packs[pack.pack_id] = pack

        if len(self.packs) < 2:
            raise RuntimeError("At least two production packs are required for treatment comparison")

    def list(self) -> list[FilmProductionPack]:
        return list(self.packs.values())

    def get(self, pack_id: str) -> FilmProductionPack:
        try:
            return self.packs[pack_id]
        except KeyError as exc:
            raise ValueError(f"Unknown production pack: {pack_id}") from exc

    def relevant(self, brief: CreativeBrief) -> list[FilmProductionPack]:
        text = " ".join([brief.logline, *brief.genre, *brief.tone]).lower()
        return sorted(
            self.packs.values(),
            key=lambda pack: sum(term.lower() in text for term in [*pack.genres, *pack.keywords]),
            reverse=True,
        )

    def validate_shots(self, shots: list[ShotSpec], pack: FilmProductionPack) -> list[GrammarIssue]:
        issues: list[GrammarIssue] = []
        grammar = pack.directing_grammar
        valid_functions = {item for sequence in grammar.sequence_patterns.values() for item in sequence}

        for shot in shots:
            if shot.grammar_pack_id != pack.pack_id:
                issues.append(GrammarIssue(
                    severity="error",
                    code="PACK_MISMATCH",
                    shot_ids=[shot.shot_id],
                    message="镜头没有绑定当前导演语法包",
                    suggested_fix=f"将 grammar_pack_id 设为 {pack.pack_id}",
                ))
            if shot.duration_seconds > pack.generation_recipe.max_duration_seconds:
                issues.append(GrammarIssue(
                    severity="error",
                    code="SHOT_TOO_LONG",
                    shot_ids=[shot.shot_id],
                    message=f"镜头时长超过工作流稳定上限 {pack.generation_recipe.max_duration_seconds:g} 秒",
                    suggested_fix="按动作边界拆成两个镜头",
                ))
            if shot.sequence_pattern not in grammar.sequence_patterns:
                issues.append(GrammarIssue(
                    severity="error",
                    code="UNKNOWN_SEQUENCE_PATTERN",
                    shot_ids=[shot.shot_id],
                    message="镜头没有使用语法包中的段落模式",
                    suggested_fix=f"选择以下模式之一：{', '.join(grammar.sequence_patterns)}",
                ))
            if shot.shot_function not in valid_functions:
                issues.append(GrammarIssue(
                    severity="error",
                    code="UNKNOWN_SHOT_FUNCTION",
                    shot_ids=[shot.shot_id],
                    message="镜头缺少明确的叙事功能",
                    suggested_fix="从所选段落模式中指定 shot_function",
                ))
            if shot.shot_size not in grammar.preferred_sizes:
                issues.append(GrammarIssue(
                    severity="warning",
                    code="DISCOURAGED_SHOT_SIZE",
                    shot_ids=[shot.shot_id],
                    message=f"景别 {shot.shot_size} 不在该语法包的优选词汇中",
                    suggested_fix="确认该景别是否承担不可替代的信息功能",
                ))

        run: list[ShotSpec] = []
        for shot in shots:
            run = [*run, shot] if run and run[-1].shot_size == shot.shot_size else [shot]
            if len(run) == grammar.max_same_size_run + 1:
                issues.append(GrammarIssue(
                    severity="warning",
                    code="REPEATED_SHOT_SIZE",
                    shot_ids=[item.shot_id for item in run],
                    message=f"连续超过 {grammar.max_same_size_run} 个相同景别",
                    suggested_fix="改变景别，或确认连续重复具有明确表达目的",
                ))
        return issues


production_pack_registry = ProductionPackRegistry()


class AuteurProfileRegistry:
    def __init__(self, profiles_dir: Optional[Path] = None):
        self.profiles_dir = profiles_dir or settings.auteur_profiles_dir
        self.profiles: dict[str, AuteurProfile] = {}
        self.load_all()

    def load_all(self) -> None:
        self.profiles.clear()
        if not self.profiles_dir.is_dir():
            raise RuntimeError(f"Auteur profile directory not found: {self.profiles_dir}")

        for path in sorted(self.profiles_dir.glob("*.yaml")):
            profile = AuteurProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            if profile.profile_id in self.profiles:
                raise ValueError(f"Duplicate auteur profile ID: {profile.profile_id}")
            variant_ids = [variant.variant_id for variant in profile.variants]
            if not variant_ids or len(variant_ids) != len(set(variant_ids)):
                raise ValueError(f"Auteur variant IDs must be non-empty and unique: {path.name}")
            if profile.default_variant_id not in variant_ids:
                raise ValueError(f"Default auteur variant not found: {path.name}")
            for variant in profile.variants:
                technique_ids = [technique.technique_id for technique in variant.techniques]
                if not technique_ids or len(technique_ids) != len(set(technique_ids)):
                    raise ValueError(f"Technique IDs must be non-empty and unique: {path.name}/{variant.variant_id}")
            self.profiles[profile.profile_id] = profile

        if not self.profiles:
            raise RuntimeError("At least one auteur profile is required")

    def list(self) -> list[AuteurProfile]:
        return list(self.profiles.values())

    def get(self, profile_id: str) -> AuteurProfile:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"Unknown auteur profile: {profile_id}") from exc

    def variant(self, profile: AuteurProfile, variant_id: Optional[str] = None) -> AuteurVariant:
        selected_id = variant_id or profile.default_variant_id
        selected = next((variant for variant in profile.variants if variant.variant_id == selected_id), None)
        if not selected:
            raise ValueError(f"Unknown auteur variant: {selected_id}")
        return selected

    def validate_shots(self, shots: list[ShotSpec], context: AuteurContext) -> list[GrammarIssue]:
        variant = self.variant(context.profile, context.selection.variant_id)
        valid_ids = {technique.technique_id for technique in variant.techniques}
        used_ids: set[str] = set()
        issues: list[GrammarIssue] = []

        for shot in shots:
            if (
                shot.auteur_profile_id != context.profile.profile_id
                or shot.auteur_variant_id != variant.variant_id
            ):
                issues.append(GrammarIssue(
                    severity="error",
                    code="AUTEUR_PROFILE_MISMATCH",
                    shot_ids=[shot.shot_id],
                    message="镜头没有绑定当前名导技法档案",
                    suggested_fix="重新应用当前档案生成镜头，或修正镜头的 profile/variant ID",
                ))
            unknown = set(shot.technique_ids) - valid_ids
            if unknown:
                issues.append(GrammarIssue(
                    severity="error",
                    code="UNKNOWN_AUTEUR_TECHNIQUE",
                    shot_ids=[shot.shot_id],
                    message=f"镜头引用了不存在的技法：{', '.join(sorted(unknown))}",
                    suggested_fix="只使用当前代表作模式中声明的 technique_id",
                ))
            used_ids.update(shot.technique_ids)

        if not used_ids:
            issues.append(GrammarIssue(
                severity="error",
                code="AUTEUR_TECHNIQUE_UNUSED",
                shot_ids=[shot.shot_id for shot in shots],
                message="选择了名导技法档案，但镜头表没有应用任何具体技法",
                suggested_fix="至少为关键镜头分配一个 technique_id 并说明作用",
            ))
        elif context.selection.intensity == "strong" and len(used_ids) < min(2, len(valid_ids)):
            issues.append(GrammarIssue(
                severity="warning",
                code="AUTEUR_INTENSITY_UNDERSERVED",
                shot_ids=[shot.shot_id for shot in shots],
                message="强技法模式只使用了一种技法",
                suggested_fix="在关键镜头中组合至少两种互补技法",
            ))
        return issues


auteur_profile_registry = AuteurProfileRegistry()
