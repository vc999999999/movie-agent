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
from agent.questions import (
    select_questions,
    apply_safe_defaults,
    calculate_priority,
    calculate_brief_completion,
)
from agent.prompt_compiler import prompt_compiler, PromptCompiler
from agent.workflow import workflow_registry, WorkflowRegistry
from agent.comfyui import comfyui_client, ComfyUIClient
from agent.continuity import continuity_checker, ContinuityChecker
from agent.llm import llm_service, LLMService
from agent.service import project_service, ProjectService

# Convenience alias for MovieAgent
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
