import { useMemo, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useQuery } from "@tanstack/react-query";
import { apiJson, encodeSeg } from "../api/client";
import type { StageId } from "../app/stages";
import { Button } from "./Button";

/* ---------- 数据类型 ---------- */

export interface PipelineStepLog {
  step: string;
  status: "pending" | "running" | "done" | "failed";
  detail?: string | null;
  error?: string;
}

interface PipelineStatusResponse {
  project_id: string;
  project_status: string;
  pipeline: { steps: PipelineStepLog[]; status: "idle" | "running" | "completed" | "failed" | "interrupted" | "needs_clarification" | "quality_failed"; task_id?: string; elapsed_seconds?: number; error: string | null };
  shots: { shot_id: string; status: string; error?: string | null }[];
  artifacts: Record<string, boolean>;
  handoffs?: { version: number; content: { role: string; task: string; elapsed_seconds: number; status?: string } }[];
  revisions?: { version: number; content: { role: string; round: number; before: { shots: { shot_id: string; action: string }[] }; after: { shots: { shot_id: string; action: string }[] } } }[];
  reused?: unknown[];
  legacy_render_notice?: boolean;
}

/** 轮询编排状态：pipeline 运行时 2s 一次，否则 10s 低频。 */
export function usePipelineStatus(projectId: string | null) {
  return useQuery({
    queryKey: ["pipeline", projectId ?? ""],
    queryFn: () => apiJson<PipelineStatusResponse>(`/api/projects/${encodeSeg(projectId!)}/auto_pipeline`),
    enabled: projectId !== null,
    refetchInterval: (query) => (query.state.data?.pipeline.status === "running" ? 2000 : 10000),
    retry: false,
  });
}

/* ---------- 树结构 ---------- */

type NodeStatus = "pending" | "running" | "done" | "failed";

interface SwarmNode {
  key: string;
  role: string;
  task: string;
  status: NodeStatus;
  error?: string | null;
  targetStage?: StageId;
}

interface SwarmLayer {
  id: string;
  nodes: SwarmNode[];
}

const stepById = (steps: PipelineStepLog[]) => new Map(steps.map((s) => [s.step, s]));

function nodeStatusOf(
  stepId: string,
  steps: PipelineStepLog[],
  artifacts: Record<string, boolean>,
  artifactKey: string,
  pipelineStatus: string,
): NodeStatus {
  const entry = stepById(steps).get(stepId);
  if (entry) {
    if (entry.status === "running") return "running";
    if (entry.status === "failed") return "failed";
    if (entry.status === "done") return "done";
  }
  if (pipelineStatus === "running") return "pending";
  return artifacts[artifactKey] ? "done" : "pending";
}

/** 从项目状态数据装配编排树（分波次 = 各生成步骤）。 */
function buildSwarmTree(
  status: PipelineStatusResponse | null | undefined,
  treatments: { options: { name: string; treatment_id: string }[] } | null | undefined,
  shotIds: string[],
  shotTitles: Map<string, string>,
): { layers: SwarmLayer[]; lead: SwarmNode; leadStatus: NodeStatus } {
  const steps = status?.pipeline.steps ?? [];
  const artifacts = status?.artifacts ?? {};
  const pstatus = status?.pipeline.status ?? "idle";
  const shotRuns = new Map((status?.shots ?? []).map((s) => [s.shot_id, s]));

  // Lead Agent 状态
  const leadStatus: NodeStatus =
    pstatus === "running" ? "running" : ["failed", "interrupted", "needs_clarification", "quality_failed"].includes(pstatus) ? "failed" : pstatus === "completed" ? "done" : "pending";

  // Wave 1: 创意分析
  const wave1: SwarmNode = {
    key: "brief",
    role: "创意分析师",
    task: "反问与创作简报锁定",
    status: artifacts.brief ? "done" : leadStatus === "running" ? "pending" : "pending",
    targetStage: "brief",
  };

  // Wave 2: 导演方案（动态生成 N 张卡）
  const options = treatments?.options ?? [];
  const wave2: SwarmNode[] =
    options.length > 0
      ? options.map((opt, i) => ({
          key: `treatment-${opt.treatment_id}`,
          role: "导演方案师",
          task: `方案 ${String.fromCharCode(65 + i)} · ${opt.name}`,
          status: nodeStatusOf("treatments", steps, artifacts, "treatments", pstatus),
          targetStage: "treatments" as StageId,
        }))
      : [
          {
            key: "treatment-pending",
            role: "导演方案师",
            task: "生成 2-3 个可比较的方案",
            status: nodeStatusOf("treatments", steps, artifacts, "treatments", pstatus),
            targetStage: "treatments" as StageId,
          },
        ];

  // Wave 3: 编剧 + 分镜 + 提示词
  const wave3: SwarmNode[] = [
    {
      key: "screenplay",
      role: "编剧",
      task: "剧本与场景圣经",
      status: nodeStatusOf("screenplay", steps, artifacts, "screenplay", pstatus),
      targetStage: "bible",
    },
    {
      key: "shots",
      role: "分镜师",
      task: "镜头拆解与连续性校验",
      status: nodeStatusOf("shots", steps, artifacts, "shots", pstatus),
      targetStage: "storyboard",
    },
    {
      key: "quality",
      role: "质检",
      task: "独立审阅与最多两轮修订",
      status: nodeStatusOf("quality", steps, artifacts, "quality", pstatus),
      targetStage: "generation",
    },
    {
      key: "packages",
      role: "提示词编译器",
      task: "Prompt 包编译与工作流注入",
      status: nodeStatusOf("packages", steps, artifacts, "packages", pstatus),
      targetStage: "generation",
    },
  ];

  // Wave 4: 渲染（每镜头一张卡）
  const renderStep = stepById(steps).get("render");
  const wave4: SwarmNode[] = shotIds.map((shotId) => {
    const run = shotRuns.get(shotId);
    let status: NodeStatus = "pending";
    let error: string | null = null;
    if (run) {
      if (run.status === "success") status = "done";
      else if (run.status === "running" || run.status === "pending") status = "running";
      else if (run.status === "failed") {
        status = "failed";
        error = run.error ?? null;
      }
    } else if (renderStep?.status === "running") {
      status = "pending";
    } else if (artifacts.rough_cut) {
      status = "done";
    }
    return {
      key: `render-${shotId}`,
      role: "渲染执行",
      task: `${shotId} · ${shotTitles.get(shotId) ?? "镜头视频生成"}`,
      status,
      error,
      targetStage: "generation" as StageId,
    };
  });
  if (wave4.length === 0) {
    wave4.push({
      key: "render-pending",
      role: "渲染执行",
      task: "待分镜生成后执行逐镜头渲染",
      status: renderStep?.status === "running" ? "running" : "pending",
      targetStage: "generation" as StageId,
    });
  }

  // Wave 5: 剪辑
  const wave5: SwarmNode = {
    key: "rough_cut",
    role: "剪辑执行",
    task: "FFmpeg 粗剪合成成片",
    status: nodeStatusOf("rough_cut", steps, artifacts, "rough_cut", pstatus),
    targetStage: "preview",
  };

  const lead: SwarmNode = {
    key: "lead",
    role: "Lead Agent",
    task: "协调全片制作任务",
    status: leadStatus,
    error: status?.pipeline.error ?? null,
  };

  return {
    lead,
    leadStatus,
    layers: [
      { id: "w1", nodes: [wave1] },
      { id: "w2", nodes: wave2 },
      { id: "w3", nodes: wave3 },
      { id: "w4", nodes: wave4 },
      { id: "w5", nodes: [wave5] },
    ],
  };
}

/* ---------- 视觉 ---------- */

const STATUS_STYLE: Record<NodeStatus, { icon: string; color: string; label: string; border: string; bg: string }> = {
  pending: { icon: "○", color: "var(--text-tertiary)", label: "待开始", border: "var(--line)", bg: "transparent" },
  running: { icon: "◐", color: "var(--info)", label: "进行中", border: "rgb(100 210 255 / 45%)", bg: "rgb(100 210 255 / 8%)" },
  done: { icon: "●", color: "var(--success)", label: "已完成", border: "rgb(48 209 88 / 35%)", bg: "rgb(48 209 88 / 8%)" },
  failed: { icon: "✕", color: "var(--danger)", label: "失败", border: "rgb(255 69 58 / 40%)", bg: "rgb(255 69 58 / 8%)" },
};

function NodeCard({ node, onClick }: { node: SwarmNode; onClick: (stage: StageId) => void }) {
  const s = STATUS_STYLE[node.status];
  const style: CSSProperties = {
    width: 210,
    padding: "12px 14px",
    display: "grid",
    gap: 6,
    textAlign: "left",
    borderRadius: 14,
    border: `1px solid ${s.border}`,
    background: node.status === "pending" ? "var(--canvas-overlay)" : s.bg,
    backdropFilter: "blur(8px)",
    cursor: node.targetStage ? "pointer" : "default",
    transition: "transform 160ms var(--spring), border-color 160ms",
  };
  return (
    <motion.button
      type="button"
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      whileHover={node.targetStage ? { y: -2, borderColor: "var(--accent-soft)" } : undefined}
      style={style}
      onClick={() => node.targetStage && onClick(node.targetStage)}
      aria-label={`${node.role}：${node.task}（${s.label}）`}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          aria-hidden="true"
          style={{
            width: 26,
            height: 26,
            borderRadius: 8,
            display: "grid",
            placeItems: "center",
            fontSize: 13,
            background: "rgb(255 255 255 / 8%)",
          }}
        >
          {node.status === "running" ? "⏳" : node.status === "failed" ? "⚠" : "🎬"}
        </span>
        <div style={{ display: "grid", gap: 1 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{node.role}</span>
          <span className="text-tertiary" style={{ fontSize: 11, lineHeight: 1.4 }}>{node.task}</span>
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: s.color }}>
        <span aria-hidden="true" className={node.status === "running" ? "pulse" : undefined}>{s.icon}</span>
        <span>{s.label}</span>
        {node.error ? (
          <span className="text-danger" style={{ fontSize: 11, marginLeft: 4 }} title={node.error}>
            {node.error.slice(0, 24)}…
          </span>
        ) : null}
      </div>
    </motion.button>
  );
}

/** 层间弧线连接（从上层 N 张卡扇形连到下层 M 张卡）。 */
function Connectors({ from, to }: { from: number; to: number }) {
  const W = 1000;
  const H = 56;
  const paths: string[] = [];
  for (let i = 0; i < from; i += 1) {
    const x1 = ((i + 0.5) / from) * W;
    for (let j = 0; j < to; j += 1) {
      const x2 = ((j + 0.5) / to) * W;
      const cy = H * 0.55;
      paths.push(`M ${x1} 0 C ${x1} ${cy}, ${x2} ${H - cy}, ${x2} ${H}`);
    }
  }
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      style={{ width: "100%", height: H, display: "block", overflow: "visible" }}
    >
      {paths.map((d, i) => (
        <path
          key={i}
          d={d}
          fill="none"
          stroke="var(--line)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          opacity={0.6}
        />
      ))}
    </svg>
  );
}

/* ---------- 主组件 ---------- */

interface PipelineSwarmProps {
  projectId: string;
  treatments?: { options: { name: string; treatment_id: string }[] } | null;
  shotIds?: string[];
  shotTitles?: Map<string, string>;
  onNavigate?: (stage: StageId) => void;
  onStart?: () => void;
  starting?: boolean;
}

export function PipelineSwarm({
  projectId,
  treatments,
  shotIds = [],
  shotTitles = new Map(),
  onNavigate,
  onStart,
  starting,
}: PipelineSwarmProps) {
  const statusQuery = usePipelineStatus(projectId);
  const status = statusQuery.data ?? null;

  const { lead, layers } = useMemo(
    () => buildSwarmTree(status, treatments, shotIds, shotTitles),
    [status, treatments, shotIds, shotTitles],
  );

  const canStart = status?.pipeline.status !== "running" && onStart !== undefined;
  const handleNavigate = (stage: StageId) => onNavigate?.(stage);

  return (
    <section className="card" style={{ padding: 20, display: "grid", gap: 0 }} aria-label="编排视图">
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 600 }}>全片编排</h3>
          <p className="text-tertiary" style={{ fontSize: 12, marginTop: 2 }}>
            角色职责概览；实际执行顺序、耗时与反馈见下方运行记录
          </p>
        </div>
        <span style={{ flex: 1 }} />
        {onStart ? (
          <Button variant="primary" size="sm" onClick={onStart} disabled={!canStart || starting}>
            {status?.pipeline.status === "running" ? "生成中…" : (status?.pipeline.status === "idle" ? "开始全自动生成" : "恢复生成")}
          </Button>
        ) : null}
      </div>

      <div style={{ display: "grid", justifyItems: "center" }}>
        <NodeCard node={lead} onClick={handleNavigate} />
        {layers.map((layer, idx) => (
          <div key={layer.id} style={{ width: "100%", display: "grid", justifyItems: "center" }}>
            <Connectors from={idx === 0 ? 1 : layers[idx - 1].nodes.length} to={layer.nodes.length} />
            <div
              style={{
                display: "flex",
                gap: 14,
                flexWrap: "wrap",
                justifyContent: "center",
                width: "100%",
              }}
            >
              <AnimatePresence mode="popLayout">
                {layer.nodes.map((node) => (
                  <NodeCard key={node.key} node={node} onClick={handleNavigate} />
                ))}
              </AnimatePresence>
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
        {status?.pipeline.task_id && <p className="text-secondary">任务 {status.pipeline.task_id.slice(0, 12)} · {status.pipeline.elapsed_seconds ?? "进行中"} 秒 · 复用 {status.reused?.length ?? 0} 次</p>}
        {status?.legacy_render_notice && <p>旧镜头缺少生成指纹，将重新验证并生成。</p>}
        {(status?.handoffs ?? []).slice(-12).map(item => <p key={item.version}>{({ producer: "制片规划", writer: "编剧", director: "分镜导演", critic: "质检", executor: "制作执行" } as Record<string, string>)[item.content.role] ?? item.content.role} · {item.content.task} · {item.content.elapsed_seconds}s · {item.content.status ?? "反馈已记录"}</p>)}
        {(status?.revisions ?? []).map(item => <details key={item.version}><summary>第 {item.content.round} 轮修订 · {item.content.role === "writer" ? "编剧" : "分镜导演"}</summary>{item.content.after.shots.map(shot => <p key={shot.shot_id}>{shot.shot_id}：{item.content.before.shots.find(old => old.shot_id === shot.shot_id)?.action} → {shot.action}</p>)}</details>)}
      </div>
      {status?.pipeline.error ? (
        <p className="text-danger" style={{ fontSize: 12, marginTop: 10 }} role="alert">
          编排失败：{status.pipeline.error}
        </p>
      ) : null}
    </section>
  );
}
