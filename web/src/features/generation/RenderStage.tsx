import { useEffect, useState } from "react";
import { encodeSeg, outputUrl } from "../../api/client";
import {
  useCompilePackages,
  usePackages,
  useRenderAll,
  useRenderRun,
  useRenderShot,
} from "../../api/queries";
import type { PackagesResponse, ShotPrompt, WorkflowPlan } from "../../api/types";
import type { StageId } from "../../app/stages";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";

import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import { useAiWait } from "../../components/useAiWait";
import { useInspector } from "../../app/App";
import { useShell } from "../../app/ShellContext";

function CollapsiblePrompt({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className="text-tertiary"
        style={{ fontSize: 11, textDecoration: "underline" }}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? "收起" : "展开"}{label}
      </button>
      <pre
        className="mono"
        style={{
          marginTop: 6,
          fontSize: 11,
          lineHeight: 1.6,
          color: "var(--text-secondary)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          background: "rgb(0 0 0 / 30%)",
          borderRadius: 8,
          padding: 10,
          maxHeight: open ? 320 : 44,
          overflow: "hidden",
          transition: "max-height 220ms var(--spring)",
        }}
      >
        {text}
      </pre>
    </div>
  );
}

const PLAN_STATUS: Record<WorkflowPlan["status"], { label: string; tone: "success" | "warning" | "danger" }> = {
  matched: { label: "工作流已匹配", tone: "success" },
  unsupported: { label: "不支持", tone: "danger" },
  precheck_failed: { label: "预检失败", tone: "danger" },
};

function ShotPackageCard({
  projectId,
  pkg,
  plan,
}: {
  projectId: string;
  pkg: ShotPrompt;
  plan: WorkflowPlan | undefined;
}) {
  const renderShot = useRenderShot(projectId);
  const [renderId, setRenderId] = useState<string | null>(null);
  const [initialStatus, setInitialStatus] = useState<string | null>(null);
  const runQuery = useRenderRun(renderId);
  const { addDockTask, updateDockTask } = useShell();
  const { toast } = useToast();
  const { withWait } = useAiWait();

  const run = runQuery.data ?? null;
  const matched = plan?.status === "matched";
  const planMeta = plan ? PLAN_STATUS[plan.status] : null;

  useEffect(() => {
    if (!run) return;
    updateDockTask(
      `render-${run.id}`,
      run.status === "pending" ? "submitted" : run.status,
      run.status === "failed" ? (typeof run.error_json?.message === "string" ? run.error_json.message : "渲染失败") : undefined,
    );
  }, [run, updateDockTask]);

  const startRender = () => {
    if (renderShot.isPending || !matched) return;
    withWait(
      {
        step: `渲染镜头 ${pkg.shot_id}`,
        detail: "云端视频模型正在生成该镜头画面，单镜头通常需要 3~10 分钟",
        expect: "免费档视频队列偶有排队",
      },
      () => renderShot.mutateAsync(pkg.shot_id),
    )
      .then((r) => {
        setRenderId(r.id);
        setInitialStatus(r.status);
        addDockTask({
          id: `render-${r.id}`,
          label: `渲染 ${pkg.shot_id}`,
          status: r.status === "pending" ? "submitted" : r.status,
        });
        if (r.status === "success") toast(`${pkg.shot_id} 渲染成功`, "success");
        if (r.status === "failed") toast(`${pkg.shot_id} 渲染失败`, "error");
      })
      .catch(() => toast("渲染请求失败", "error"));
  };

  const activeStatus = run?.status ?? (renderShot.data && renderId === renderShot.data.id ? renderShot.data.status : initialStatus);
  const failedMessage =
    activeStatus === "failed"
      ? typeof run?.error_json?.message === "string"
        ? run.error_json.message
        : "渲染失败"
      : null;

  return (
    <article className="card" style={{ padding: 18, display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <strong className="mono" style={{ fontSize: 14 }}>{pkg.shot_id}</strong>
        {planMeta ? <StatusBadge tone={planMeta.tone} label={planMeta.label} /> : null}
        {plan?.workflow_id ? <span className="tag mono" style={{ fontSize: 11 }}>{plan.workflow_id}</span> : null}
        <span style={{ flex: 1 }} />
        {matched ? (
          <a
            className="tag hover-lift"
            href={`/api/projects/${encodeSeg(projectId)}/workflow/${encodeSeg(pkg.shot_id)}`}
            download
          >
            下载 API 工作流
          </a>
        ) : null}
      </div>

      {plan && plan.status !== "matched" && plan.reason ? (
        <ErrorNotice
          title={`镜头 ${pkg.shot_id} 无法进入生成`}
          impact={plan.reason}
          actions={<span className="text-tertiary" style={{ fontSize: 12 }}>返回分镜编辑以调整该镜头。</span>}
        />
      ) : null}

      <CollapsiblePrompt label="正向 Prompt" text={pkg.positive_prompt} />
      <CollapsiblePrompt label="负向 Prompt" text={pkg.negative_prompt} />

      <div style={{ display: "flex", gap: 16, fontSize: 12, flexWrap: "wrap" }} className="text-secondary">
        <span>分辨率 <strong className="mono">{pkg.width}×{pkg.height}</strong></span>
        <span>帧数 <strong className="mono">{pkg.frame_count}</strong></span>
        <span>FPS <strong className="mono">{pkg.fps}</strong></span>
        <span>Seed <strong className="mono">{pkg.seed}</strong></span>
        {pkg.steps !== null ? <span>Steps <strong className="mono">{pkg.steps}</strong></span> : null}
        {pkg.cfg !== null ? <span>CFG <strong className="mono">{pkg.cfg}</strong></span> : null}
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <Button variant="primary" size="sm" onClick={startRender} disabled={!matched || renderShot.isPending || activeStatus === "pending" || activeStatus === "running"}>
          {renderShot.isPending || activeStatus === "pending" || activeStatus === "running" ? "渲染中…" : "渲染镜头"}
        </Button>
        <div style={{ flex: 1, minWidth: 200 }}>
          {activeStatus === "success" ? (
            <video
              src={outputUrl(projectId, `${pkg.shot_id}.mp4`)}
              controls
              loop
              muted
              preload="metadata"
              style={{ width: "100%", maxWidth: 380, borderRadius: 10, border: "1px solid var(--line)" }}
            />
          ) : failedMessage ? (
            <p className="text-danger" style={{ fontSize: 12 }} role="alert">渲染失败：{failedMessage}</p>
          ) : activeStatus === "pending" || activeStatus === "running" ? (
            <p className="text-tertiary" style={{ fontSize: 12 }} aria-live="polite">任务已提交，正在等待服务器响应…</p>
          ) : (
            <p className="text-tertiary" style={{ fontSize: 12 }}>尚未生成</p>
          )}
        </div>
      </div>
    </article>
  );
}

export function RenderStage({ projectId }: { projectId: string }) {
  const packagesQuery = usePackages(projectId, true);
  const compilePackages = useCompilePackages(projectId);
  const renderAll = useRenderAll(projectId);

  const { addDockTask, updateDockTask } = useShell();
  const { toast } = useToast();
  const { withWait } = useAiWait();

  const data: PackagesResponse | null = packagesQuery.data ?? null;
  const pkgs = data?.prompt_packages ?? [];
  const plans = data?.workflow_plans ?? [];
  const planByShot = new Map(plans.map((p) => [p.shot_id, p]));
  const matchedCount = plans.filter((p) => p.status === "matched").length;
  const navigateStage = (stage: StageId) =>
    window.dispatchEvent(new CustomEvent("movie-agent:navigate-stage", { detail: stage }));

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>生成上下文</h3>
      {data ? (
        <>
          <p className="text-secondary" style={{ fontSize: 12 }}>
            {pkgs.length} 个 Prompt 包 · {matchedCount}/{plans.length} 工作流已编译。
          </p>
          <p className="text-tertiary" style={{ fontSize: 12 }}>
            单镜头渲染会轮询真实状态；批量渲染为长请求，任务坞只显示“已提交/等待服务器响应”，不显示伪造进度。
          </p>
        </>
      ) : (
        <p className="text-tertiary" style={{ fontSize: 12 }}>确认镜头表后，这里会显示工作流预检与渲染状态。</p>
      )}
    </div>,
    [data, pkgs.length, matchedCount, plans.length],
  );

  const startBatch = () => {
    if (renderAll.isPending) return;
    const taskId = `batch-${Date.now()}`;
    addDockTask({ id: taskId, label: "批量渲染全部镜头", status: "submitted", detail: "等待服务器响应" });
    withWait(
      {
        step: "批量渲染全部镜头",
        detail: "云端模型逐镜头生成中，每个镜头需要数分钟，请耐心等待",
        expect: "全程可能超过 20 分钟",
      },
      () => renderAll.mutateAsync(),
    )
      .then((runs) => {
        const failed = runs.filter((r) => r.status === "failed").length;
        updateDockTask(taskId, failed > 0 ? "failed" : "success", `${runs.length - failed}/${runs.length} 成功`);
        toast(failed > 0 ? `批量渲染完成，${failed} 个失败` : "批量渲染全部成功", failed > 0 ? "error" : "success");
        void packagesQuery.refetch();

      })
      .catch((err) => {
        updateDockTask(taskId, "failed", err?.message ?? "请求失败");
        toast("批量渲染请求失败", "error");
      });
  };

  if (packagesQuery.isLoading) {
    return <p className="text-tertiary" aria-live="polite">正在载入生成包…</p>;
  }

  if (packagesQuery.isError || !data || pkgs.length === 0) {
    return (
      <div style={{ display: "grid", gap: 16 }}>
        <div className="card" style={{ padding: 24, display: "grid", gap: 12, maxWidth: 520 }}>
          <h2 className="display" style={{ fontSize: 20 }}>可选在线渲染</h2>
          <p className="text-secondary" style={{ fontSize: 13 }}>
            还没有编译好的 Prompt 包。确认镜头表后，在此编译工作流参数。
          </p>
          {compilePackages.isError ? (
            <ErrorNotice title="编译生成包失败" error={compilePackages.error} />
          ) : null}
          <div>
            <Button
              variant="primary"
              onClick={() =>
                withWait(
                  { step: "编译 Prompt 包", detail: "AI 正在为每个镜头拼装 8 层提示词", expect: "通常需要 10~40 秒" },
                  () => compilePackages.mutateAsync(),
                ).catch((err) => toast("编译失败：" + (err?.message ?? "未知错误"), "error"))
              }
              disabled={compilePackages.isPending}
            >
              {compilePackages.isPending ? "正在编译…" : "编译 Prompt 包与工作流"}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <p className="text-secondary">可选：连接服务器的生成服务后在线渲染。导出工作流不需要执行此步骤。</p>
      <Button onClick={() => navigateStage("preview")}>打开粗剪预览</Button>

      <header style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h2 className="display" style={{ fontSize: 22 }}>可选在线渲染</h2>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
            {pkgs.length} 个镜头 · {matchedCount} 个工作流已编译
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <Button
          variant="ghost"
          onClick={() =>
            withWait(
              { step: "重新编译 Prompt 包", expect: "通常需要 10~40 秒" },
              () => compilePackages.mutateAsync(),
            ).catch((err) => toast("编译失败：" + (err?.message ?? "未知错误"), "error"))
          }
          disabled={compilePackages.isPending}
        >
          {compilePackages.isPending ? "重新编译中…" : "重新编译"}
        </Button>
        <Button variant="primary" onClick={startBatch} disabled={renderAll.isPending || matchedCount === 0}>
          {renderAll.isPending ? "批量渲染已提交…" : "批量渲染全部"}
        </Button>
      </header>

      {pkgs.map((p) => (
        <ShotPackageCard key={p.shot_id} projectId={projectId} pkg={p} plan={planByShot.get(p.shot_id)} />
      ))}
    </div>
  );
}
