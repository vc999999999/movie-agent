"""Movie Agent Core SDK - Headless AI Film Production Engine."""

from agent.models import (
    CreativeBrief,
    ProjectBible,
    CharacterBible,
    LocationBible,
    SceneSpec,
    ShotSpec,
    ShotPrompt,
    WorkflowProfile,
    ContinuityIssue,
    RenderRun,
)
from agent.prompt_compiler import prompt_compiler
from agent.workflow import workflow_registry
from agent.comfyui import comfyui_client
from agent.continuity import continuity_checker
from agent.llm import llm_service
from agent.service import project_service, ProjectService

MovieAgent = ProjectService

__all__ = [
    "MovieAgent",
    "ProjectService",
    "project_service",
    "CreativeBrief",
    "ProjectBible",
    "CharacterBible",
    "LocationBible",
    "SceneSpec",
    "ShotSpec",
    "ShotPrompt",
    "WorkflowProfile",
    "ContinuityIssue",
    "RenderRun",
    "prompt_compiler",
    "workflow_registry",
    "comfyui_client",
    "continuity_checker",
    "llm_service",
]
