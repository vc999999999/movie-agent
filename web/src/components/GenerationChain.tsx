import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "../api/client";
import { Button } from "./Button";

export interface PipelineStepLog {
  step: string;
  status: "pending" | "running" | "done" | "failed";
  detail?: string | null;
  error?: string;
}

interface PipelineResponse {
  project_id: string;
  steps: PipelineStepLog[];
  status: string;
}

export const PIPELINE_STEP_LABELS: Record<string, string> = {
  treatments: "导演方案生成",
  treatment_choice: "方案选定（自动推荐）",
  screenplay: "剧本与场景",
  shots: "分镜镜头表",
  packages: "Prompt 包编译",
  render: "镜头渲染",
  rough_cut: "粗剪合成",
};

/** Long-running one-click generation chain (backend drives all steps). */
export function useAutoPipeline(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<PipelineResponse>(`/api/projects/${projectId}/auto_pipeline`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["project", projectId] });
      void qc.invalidateQueries({ queryKey: ["shots", projectId] });
      void qc.invalidateQueries({ queryKey: ["packages", projectId] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

interface GenerationChainProps {
  running: boolean;
  log: PipelineStepLog[];
  onStart: () => void;
  disabled?: boolean;
  disabledReason?: string;
}

const stateIcon: Record<string, string> = {
  pending: "○",
  running: "◐",
  done: "●",
  failed: "✕",
};

const stateColor: Record<string, string> = {
  pending: "var(--text-tertiary)",
  running: "var(--info)",
  done: "var(--success)",
  failed: "var(--danger)",
};

/**
 * 生成集: one-click chain across every remaining production step.
 * Shows a live step list; the backend runs treatments → screenplay → shots
 * → packages → render → rough cut in order and reports per-step progress.
 */
export function GenerationChain({ running, log, onStart, disabled, disabledReason }: GenerationChainProps) {
  return (
    <section
      className="card"
      style={{ padding: 20, display: "grid", gap: 14 }}
      aria-label="生成集"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 600 }}>生成集 · 一键成片</h3>
          <p className="text-tertiary" style={{ fontSize: 12, marginTop: 2 }}>
            自动完成 方案 → 剧本 → 分镜 → 编译 → 渲染 → 粗剪 全部剩余步骤
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <Button variant="primary" onClick={onStart} disabled={running || disabled}>
          {running ? "生成中…" : "开始全自动生成"}
        </Button>
      </div>

      {disabled && disabledReason ? (
        <p className="text-tertiary" style={{ fontSize: 12 }}>{disabledReason}</p>
      ) : null}

      {log.length > 0 ? (
        <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
          {log.map((entry, i) => (
            <li key={`${entry.step}-${i}`} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
              <span
                aria-hidden="true"
                style={{ color: stateColor[entry.status] ?? "var(--text-tertiary)", fontSize: 13 }}
              >
                {stateIcon[entry.status] ?? "○"}
              </span>
              <span style={{ fontSize: 13, minWidth: 120 }} className={entry.status === "pending" ? "text-tertiary" : ""}>
                {PIPELINE_STEP_LABELS[entry.step] ?? entry.step}
              </span>
              <span className="text-secondary" style={{ fontSize: 12, flex: 1 }}>
                {entry.status === "running" && "进行中…"}
                {entry.status === "done" && (entry.detail ?? "完成")}
                {entry.status === "failed" && <span className="text-danger">{entry.error ?? "失败"}</span>}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
