import type { ProjectStatus } from "../api/types";

export type StageId =
  | "brief"
  | "auteur"
  | "treatments"
  | "bible"
  | "storyboard"
  | "generation"
  | "preview";

export interface StageDef {
  id: StageId;
  index: number;
  label: string;
  short: string;
}

export const STAGES: StageDef[] = [
  { id: "brief", index: 0, label: "创意 Brief", short: "创意" },
  { id: "auteur", index: 1, label: "导演技法", short: "技法" },
  { id: "treatments", index: 2, label: "导演方案", short: "方案" },
  { id: "bible", index: 3, label: "剧本圣经", short: "圣经" },
  { id: "storyboard", index: 4, label: "分镜", short: "分镜" },
  { id: "generation", index: 5, label: "生成工作台", short: "生成" },
  { id: "preview", index: 6, label: "粗剪预览", short: "粗剪" },
];

// Backend status -> furthest reachable stage (方案 §3 映射)
export function maxStageIndex(status: ProjectStatus): number {
  switch (status) {
    case "collecting":
      return 0;
    case "brief_review":
      return 1;
    case "treatment_review":
      return 2;
    case "screenplay_ready":
      return 3;
    case "shots_review":
      return 4;
    case "package_ready":
    case "rendering":
      return 5;
    case "completed":
    case "failed":
      return 6;
  }
}

export function isStageId(value: string | null): value is StageId {
  return value !== null && STAGES.some((s) => s.id === value);
}
