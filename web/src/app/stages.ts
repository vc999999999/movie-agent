import type { ProjectStatus } from "../api/types";

export type StageId = "brief" | "auteur" | "treatments" | "bible" | "storyboard" | "generation" | "render" | "preview";
export interface StageDef { id: StageId; index: number; label: string; short: string; }
export const STAGES: StageDef[] = [
  { id: "brief", index: 0, label: "剧情拆解", short: "拆解" },
  { id: "auteur", index: 1, label: "导演模板", short: "模板" },
  { id: "treatments", index: 2, label: "导演方案", short: "方案" },
  { id: "storyboard", index: 3, label: "制作流程", short: "制作" },
  { id: "generation", index: 4, label: "导出工作流", short: "导出" },
];
export function maxStageIndex(status: ProjectStatus): number {
  switch (status) {
    case "collecting": case "brief_review": return 0;
    case "director_review": return 2;
    case "treatment_review": return 2;
    case "screenplay_ready": case "shots_review": return 3;
    case "package_ready": case "rendering": case "completed": case "failed": return 4;
    default: return 0;
  }
}
export function stageIndex(stage: StageId): number {
  if (stage === "bible") return 3;
  if (stage === "render" || stage === "preview") return 4;
  return STAGES.find(s => s.id === stage)?.index ?? 0;
}
export function isStageId(value: string | null): value is StageId {
  return value !== null && [...STAGES.map(s => s.id), "bible", "render", "preview"].includes(value);
}
export function navigateStage(stage: StageId) {
  window.dispatchEvent(new CustomEvent("movie-agent:navigate-stage", { detail: stage }));
}
