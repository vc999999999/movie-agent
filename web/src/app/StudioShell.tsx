import { DemoNotice } from "../components/DemoNotice";
import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { STAGES, type StageId } from "./stages";
import type { Project } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { useShell, type DockTaskStatus } from "./ShellContext";
import { AiWaitOverlay } from "../components/AiWaitOverlay";
import "./shell.css";

const STATUS_LABEL: Record<string, { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" | "info" }> = {
  collecting: { label: "理解创意中", tone: "info" },
  brief_review: { label: "待确认 Brief", tone: "accent" },
  director_review: { label: "待选择导演模板", tone: "accent" },
  treatment_review: { label: "待选择方案", tone: "accent" },
  screenplay_ready: { label: "待生成制作流程", tone: "info" },
  shots_review: { label: "待确认分镜", tone: "accent" },
  package_ready: { label: "制作包已生成", tone: "info" },
  rendering: { label: "渲染中", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

const DOCK_STATUS_LABEL: Record<DockTaskStatus, { label: string; tone: "warning" | "info" | "success" | "danger" }> = {
  submitted: { label: "已提交", tone: "warning" },
  running: { label: "运行中", tone: "info" },
  success: { label: "成功", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

interface StudioShellProps {
  project: Project | null;
  stage: StageId;
  maxStageIndex: number;
  onSelectStage: (stage: StageId) => void;
  onNewProject: () => void;
  children: ReactNode;
}

export function StudioShell({ project, stage, maxStageIndex, onSelectStage, onNewProject, children }: StudioShellProps) {
  const { inspector, inspectorOpen, setInspectorOpen, dockTasks, clearFinishedDockTasks, aiWait } = useShell();
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [dockOpen, setDockOpen] = useState(false);

  const activeCount = dockTasks.filter((t) => t.status === "submitted" || t.status === "running").length;
  const statusMeta = project ? STATUS_LABEL[project.status] : null;

  const shellClass = [
    "shell",
    railCollapsed ? "rail-collapsed" : "",
    inspector ? "" : "no-inspector",
  ].join(" ");

  const rail = (
    <>
      {STAGES.map((s) => {
        const reachable = s.index <= maxStageIndex;
        const isActive = s.id === stage;
        const isDone = s.index < maxStageIndex && !(project?.status === "director_review" && s.index > 0);
        return (
          <button
            key={s.id}
            type="button"
            className={`rail-item ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}
            disabled={!reachable}
            aria-current={isActive ? "step" : undefined}
            onClick={() => onSelectStage(s.id)}
            title={s.label}
          >
            {isActive ? <motion.span layoutId="rail-indicator" className="rail-indicator" transition={{ type: "spring", stiffness: 300, damping: 30 }} /> : null}
            <span className="rail-num">{String(s.index + 1).padStart(2, "0")}</span>
            <span className="rail-label">{s.label}</span>
          </button>
        );
      })}
    </>
  );

  return (
    <div className={shellClass}>
      <header className="shell-topbar glass-strong">
        <strong className="display" style={{ fontSize: 16 }}>幕间</strong><DemoNotice />
        {project ? (
          <>
            <span className="mono text-tertiary project-id" style={{ fontSize: 12 }}>{project.id}</span>
            <span className="project-title" style={{ fontSize: 13 }}>{project.title || "未命名项目"}</span>
            {statusMeta ? <span className="project-state"><StatusBadge tone={statusMeta.tone} label={statusMeta.label} /></span> : null}
          </>
        ) : (
          <span className="text-tertiary" style={{ fontSize: 13 }}>未打开项目</span>
        )}
        <div style={{ flex: 1 }} />
        {inspector ? (
          <button
            type="button"
            className="tag hover-lift"
            onClick={() => setInspectorOpen(!inspectorOpen)}
            aria-pressed={inspectorOpen}
          >
            检查器
          </button>
        ) : null}
        <button type="button" className="tag hover-lift rail-toggle" onClick={() => setRailCollapsed((v) => !v)}>
          {railCollapsed ? "展开阶段栏" : "收起阶段栏"}
        </button>
        <button type="button" className="tag tag-accent hover-lift" onClick={onNewProject}>
          新项目
        </button>
      </header>

      <nav className="shell-rail glass" aria-label="制作阶段">
        {rail}
        {maxStageIndex >= 4 ? <button type="button" className="rail-item optional-navigation" onClick={() => onSelectStage("render")}>可选 · 在线渲染</button> : null}
      </nav>

      <main className="shell-canvas scrollable">
        <div className="shell-canvas-inner">{children}</div>
      </main>

      {inspector ? (
        <aside className={`shell-inspector glass ${inspectorOpen ? "open" : ""}`} aria-label="上下文检查器">
          <button className="tag inspector-close" type="button" onClick={() => setInspectorOpen(false)}>关闭说明</button>
          {inspector}
        </aside>
      ) : null}

      <nav className="mobile-stage-nav glass-strong" aria-label="制作阶段">
        {rail}
        {maxStageIndex >= 4 ? <button type="button" className="rail-item optional-navigation" onClick={() => onSelectStage("render")}>可选 · 在线渲染</button> : null}
      </nav>

      <motion.div
        className="shell-dock glass-strong"
        initial={false}
        animate={{ height: dockOpen ? "var(--dock-h-open)" : "var(--dock-h)" }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
      >
        <button
          type="button"
          onClick={() => setDockOpen((v) => !v)}
          aria-expanded={dockOpen}
          style={{
            width: "100%",
            height: "var(--dock-h)",
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "0 20px",
          }}
        >
          <strong style={{ fontSize: 13 }}>可选渲染任务</strong>
          {activeCount > 0 ? <StatusBadge tone="warning" label={`${activeCount} 个进行中`} /> : null}
          <span className="text-tertiary" style={{ fontSize: 12 }}>
            {dockTasks.length === 0 ? "暂无任务" : `共 ${dockTasks.length} 个任务`}
          </span>
          <span style={{ flex: 1 }} />
          <span className="text-tertiary" style={{ fontSize: 12 }}>{dockOpen ? "收起 ▾" : "展开 ▴"}</span>
        </button>
        {dockOpen ? (
          <div className="scrollable" style={{ height: "calc(var(--dock-h-open) - var(--dock-h))", padding: "4px 20px 16px" }}>
            {dockTasks.length === 0 ? (
              <p className="text-tertiary" style={{ fontSize: 13, paddingTop: 12 }}>
                批量渲染与单镜头渲染任务会出现在这里。
              </p>
            ) : (
              <>
                <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
                  <button type="button" className="text-tertiary" style={{ fontSize: 12, textDecoration: "underline" }} onClick={clearFinishedDockTasks}>
                    清除已完成
                  </button>
                </div>
                <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
                  <AnimatePresence initial={false}>
                    {dockTasks.map((task) => {
                      const meta = DOCK_STATUS_LABEL[task.status];
                      return (
                        <motion.li
                          key={task.id}
                          layout
                          initial={{ opacity: 0, y: -6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                          className="card"
                          style={{ padding: "8px 14px", display: "flex", alignItems: "center", gap: 12, borderRadius: "var(--radius-control)" }}
                        >
                          <span className="mono" style={{ fontSize: 12 }}>{task.label}</span>
                          <StatusBadge tone={meta.tone} label={meta.label} />
                          {task.detail ? <span className="text-tertiary" style={{ fontSize: 12 }}>{task.detail}</span> : null}
                        </motion.li>
                      );
                    })}
                  </AnimatePresence>
                </ul>
              </>
            )}
          </div>
        ) : null}
      </motion.div>
      <AiWaitOverlay state={aiWait} />
    </div>
  );
}
