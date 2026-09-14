from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Optional
import yaml

from server.config import settings
from agent.models import ErrorDetail, ShotPrompt, ShotSpec, WorkflowPlan, WorkflowProfile

logger = logging.getLogger(__name__)

class WorkflowRegistry:
    def __init__(self, workflows_dir: Optional[Path] = None):
        self.workflows_dir = workflows_dir or settings.workflows_dir
        self.profiles: dict[str, WorkflowProfile] = {}
        self.patch_maps: dict[str, dict[str, Any]] = {}
        self.raw_workflows: dict[str, dict[str, Any]] = {}
        self.prompt_rules: dict[str, dict[str, Any]] = {}
        self.load_all()

    def load_all(self) -> None:
        self.profiles.clear()
        self.patch_maps.clear()
        self.raw_workflows.clear()
        self.prompt_rules.clear()

        if not self.workflows_dir.exists():
            return

        for wf_dir in self.workflows_dir.iterdir():
            if not wf_dir.is_dir():
                continue
            profile_path = wf_dir / "profile.json"
            patch_map_path = wf_dir / "patch_map.json"
            workflow_path = wf_dir / "workflow_api.json"
            rules_path = wf_dir / "prompt_rules.yaml"

            if profile_path.exists() and patch_map_path.exists() and workflow_path.exists():
                try:
                    with open(profile_path, "r", encoding="utf-8") as f:
                        prof_data = json.load(f)
                    profile = WorkflowProfile(**prof_data)

                    with open(patch_map_path, "r", encoding="utf-8") as f:
                        patch_map = json.load(f)

                    with open(workflow_path, "r", encoding="utf-8") as f:
                        raw_wf = json.load(f)

                    rules = {}
                    if rules_path.exists():
                        with open(rules_path, "r", encoding="utf-8") as f:
                            rules = yaml.safe_load(f) or {}

                    self.profiles[profile.workflow_id] = profile
                    self.patch_maps[profile.workflow_id] = patch_map
                    self.raw_workflows[profile.workflow_id] = raw_wf
                    self.prompt_rules[profile.workflow_id] = rules
                except Exception as e:
                    logger.error(f"Error loading workflow template {wf_dir.name}: {e}")

    def get_profile(self, workflow_id: str) -> Optional[WorkflowProfile]:
        return self.profiles.get(workflow_id)

    def get_patch_map(self, workflow_id: str) -> Optional[dict[str, Any]]:
        return self.patch_maps.get(workflow_id)

    def get_raw_workflow(self, workflow_id: str) -> Optional[dict[str, Any]]:
        return copy.deepcopy(self.raw_workflows.get(workflow_id))

    def get_prompt_rules(self, workflow_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.prompt_rules.get(workflow_id, {}))

    # 9.3 Workflow selection algorithm
    def select_workflow(
        self,
        shot: ShotSpec,
        aspect_ratio: str,
        comfyui_installed_nodes: Optional[set[str]] = None,
        preferred_workflow_id: Optional[str] = None,
        check_environment: bool = True,
    ) -> WorkflowPlan:
        available_vram_gb = settings.comfyui_vram_gb
        candidates: list[WorkflowProfile] = []

        # 1. Match generation_mode
        for prof in self.profiles.values():
            if (
                prof.generation_mode == shot.generation_mode
                and (not preferred_workflow_id or prof.workflow_id == preferred_workflow_id)
            ):
                candidates.append(prof)

        if not candidates:
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=None,
                status="unsupported",
                reason=f"没有支持 {shot.generation_mode} 模式的工作流模板",
                required_capabilities=[shot.generation_mode],
            )

        # 2. Check reference requirements (first_frame, last_frame, character)
        ref_filtered: list[WorkflowProfile] = []
        required_refs = []
        if shot.first_frame_required:
            required_refs.append("first_frame")
        if shot.last_frame_required:
            required_refs.append("last_frame")
        if shot.reference_asset_ids:
            required_refs.append("character")

        for prof in candidates:
            missing_ref = False
            for req in required_refs:
                if req not in prof.accepted_references:
                    missing_ref = True
                    break
            if not missing_ref:
                ref_filtered.append(prof)

        if not ref_filtered:
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=None,
                status="unsupported",
                reason=f"镜头需要参考能力 {required_refs}，当前可用模板不支持",
                required_capabilities=required_refs,
            )

        # 3. Check aspect ratio and frame count
        aspect_filtered: list[WorkflowProfile] = []
        for prof in ref_filtered:
            if aspect_ratio in prof.supported_aspect_ratios:
                aspect_filtered.append(prof)

        if not aspect_filtered:
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=None,
                status="unsupported",
                reason=f"模板不支持画幅比例 {aspect_ratio}",
                required_capabilities=[f"aspect_ratio_{aspect_ratio}"],
            )

        requested_frames = round(shot.duration_seconds * shot.fps)
        frame_filtered = [
            p for p in aspect_filtered
            if p.generation_mode == "text_to_image" or requested_frames <= p.max_frames
        ]
        if not frame_filtered:
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=None,
                status="unsupported",
                reason=f"镜头需要 {requested_frames} 帧，当前模板上限不足",
                required_capabilities=[f"max_frames_{requested_frames}"],
            )

        # 4. Check VRAM
        vram_filtered = [p for p in frame_filtered if not check_environment or p.min_vram_gb <= available_vram_gb]
        if not vram_filtered:
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=None,
                status="precheck_failed",
                reason=f"可用显存 {available_vram_gb}GB 低于工作流最低要求",
                required_capabilities=[f"vram_gb_{min(p.min_vram_gb for p in frame_filtered)}"],
            )

        # 5. Check dependencies if provided
        dependency_failures: list[str] = []
        for prof in vram_filtered:
            if comfyui_installed_nodes is not None:
                missing_nodes = [n for n in prof.required_nodes if n not in comfyui_installed_nodes]
                if missing_nodes:
                    dependency_failures.extend(missing_nodes)
                    continue

            # Matched!
            return WorkflowPlan(
                shot_id=shot.shot_id,
                workflow_id=prof.workflow_id,
                status="matched",
                reason=None,
                required_capabilities=[],
            )

        return WorkflowPlan(
            shot_id=shot.shot_id,
            workflow_id=None,
            status="precheck_failed",
            reason=f"ComfyUI 环境缺少工作流依赖: {sorted(set(dependency_failures))}",
            required_capabilities=sorted(set(dependency_failures)),
        )

    # 9.2 Deterministic PatchMap patching
    def patch_workflow(
        self,
        workflow_id: str,
        prompt_pkg: ShotPrompt,
        first_frame_asset_path: Optional[str] = None,
        last_frame_asset_path: Optional[str] = None,
        output_file_path: Optional[Path] = None,
    ) -> tuple[dict[str, Any], Optional[ErrorDetail]]:
        patch_map = self.get_patch_map(workflow_id)
        raw_wf = self.get_raw_workflow(workflow_id)

        if not self.get_profile(workflow_id) or not patch_map or not raw_wf:
            return {}, ErrorDetail(
                code="WORKFLOW_NOT_FOUND",
                message=f"工作流模板 {workflow_id} 未在系统中登记",
                details={"workflow_id": workflow_id},
                retryable=False,
                suggested_action="检查 workflows/ 目录中的模板配置文件",
            )

        # get_raw_workflow already returns a deep copy.
        patched = raw_wf

        # Value provider dictionary
        param_values: dict[str, Any] = {
            "positive_prompt": prompt_pkg.positive_prompt,
            "negative_prompt": prompt_pkg.negative_prompt,
            "seed": prompt_pkg.seed,
            "steps": prompt_pkg.steps,
            "cfg": prompt_pkg.cfg,
            "width": prompt_pkg.width,
            "height": prompt_pkg.height,
            "frame_count": prompt_pkg.frame_count,
            "fps": prompt_pkg.fps,
            "preview_fps": prompt_pkg.fps,
            "first_frame": first_frame_asset_path,
            "last_frame": last_frame_asset_path,
        }

        # Apply patches
        for param_key, patch_info in patch_map.items():
            node_id = str(patch_info["node"])
            input_name = patch_info["input"]
            required = patch_info.get("required", False)

            # Precheck: node exists
            if node_id not in patched:
                return {}, ErrorDetail(
                    code="PATCH_TARGET_NODE_MISSING",
                    message=f"PatchMap 指向的节点 ID '{node_id}' 在 workflow JSON 中不存在",
                    details={"param": param_key, "node": node_id},
                    retryable=False,
                    suggested_action=f"核对 workflows/{workflow_id}/patch_map.json 与 workflow_api.json 的节点映射",
                )

            node = patched[node_id]
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or input_name not in inputs:
                return {}, ErrorDetail(
                    code="PATCH_TARGET_INPUT_MISSING",
                    message=f"节点 '{node_id}' 不存在输入 '{input_name}'",
                    details={"param": param_key, "node": node_id, "input": input_name},
                    retryable=False,
                    suggested_action=f"核对 workflows/{workflow_id}/patch_map.json",
                )

            val = param_values.get(param_key)
            if val is None or val == "":
                if required:
                    return {}, ErrorDetail(
                        code="REQUIRED_PARAMETER_MISSING",
                        message=f"工作流必需参数 '{param_key}' 缺失或为空",
                        details={"param": param_key, "node": node_id, "input": input_name},
                        retryable=False,
                        suggested_action=f"确保镜头提供了有效参数 {param_key}",
                    )
                else:
                    continue  # Optional parameter, skip

            # Write value
            inputs[input_name] = val

        # Save to file if path is specified
        if output_file_path:
            output_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file_path, "w", encoding="utf-8") as f:
                json.dump(patched, f, ensure_ascii=False, indent=2)

        return patched, None

workflow_registry = WorkflowRegistry()
