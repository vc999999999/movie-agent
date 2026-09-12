import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, encodeSeg } from "../../api/client";
import { queryKeys } from "../../api/queries";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { navigateStage } from "../../app/stages";
import { StoryboardStage } from "./StoryboardStage";
import { BibleStage } from "../bible/BibleStage";

interface Progress {
  pipeline: { status: string; error: string | null; steps: { step: string; status: string; error?: string }[] };
  artifacts: { screenplay: boolean; shots: boolean; packages: boolean };
}
const STEPS = [{ id: "screenplay", label: "角色、场景与剧本" }, { id: "shots", label: "分镜与连续性检查" }, { id: "packages", label: "提示词与 ComfyUI 工作流" }];
export function ProductionStage({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState("shots");
  const progress = useQuery({ queryKey: ["production-progress", projectId], queryFn: () => apiJson<Progress>(`/api/projects/${encodeSeg(projectId)}/auto_pipeline`), refetchInterval: q => q.state.data?.pipeline.status === "running" ? 1500 : false });
  const run = useMutation({ mutationFn: () => apiJson(`/api/projects/${encodeSeg(projectId)}/auto_pipeline`, { method: "POST" }), onSuccess: () => { void progress.refetch(); } });
  const data = progress.data;
  const running = data?.pipeline.status === "running" || run.isPending;
  useEffect(() => {
    if (!data || running) return;
    for (const key of [queryKeys.project(projectId), queryKeys.screenplay(projectId), queryKeys.shots(projectId), queryKeys.packages(projectId)]) void qc.invalidateQueries({ queryKey: key });
  }, [data?.pipeline.status, data?.artifacts.packages, running, projectId, qc]);
  return <div className="production-page">
    <header className="production-heading"><div><p className="eyebrow">PRODUCTION / 制作流程</p><h1 className="display">把选定的故事变成制作文件</h1><p className="text-secondary">角色设定、剧本、分镜与提示词将在这里生成。你可以审阅、修改，再导出。</p></div>
      {data?.artifacts.packages && !running ? <Button variant="primary" onClick={() => navigateStage("generation")}>审阅并导出工作流</Button> : null}
    </header>
    <section className="production-progress" aria-label="制作进度" aria-live="polite">
      {STEPS.map(step => {
        const logs = data?.pipeline.steps.filter(s => s.step === step.id) ?? [];
        const latest = logs[logs.length - 1]?.status;
        const exists = data?.artifacts[step.id as keyof Progress["artifacts"]];
        const state = running ? latest ?? (exists ? "done" : "pending") : exists ? "done" : latest === "failed" ? "failed" : "pending";
        return <div key={step.id} className={`production-step ${state}`}><span className="mono">{state === "done" ? "✓" : state === "running" ? "…" : state === "failed" ? "!" : "○"}</span><span>{step.label}</span><small>{state === "done" ? "已生成" : state === "running" ? "生成中" : state === "failed" ? "失败" : "待生成"}</small></div>;
      })}
    </section>
    {progress.isError ? <ErrorNotice title="无法读取制作进度" error={progress.error} actions={<Button onClick={() => void progress.refetch()}>重试</Button>} /> : null}
    {data?.pipeline.error ? <ErrorNotice title="制作流程尚未完成" impact={data.pipeline.error} /> : null}
    {run.isError ? <ErrorNotice title="无法启动制作流程" error={run.error} /> : null}
    {running ? <p className="text-secondary" role="status">正在按你确认的导演方案生成。可以稍后回来，进度会自动更新。</p> : data && !data.artifacts.packages ? <Button variant="primary" onClick={() => run.mutate()}>{data.pipeline.status === "failed" ? "重试未完成步骤" : "生成制作流程"}</Button> : null}
    {data?.artifacts.shots && !running ? <>
      <nav className="production-tabs" aria-label="制作资料"><Button variant={tab === "shots" ? "primary" : "ghost"} onClick={() => setTab("shots")}>分镜与检查</Button><Button variant={tab === "bible" ? "primary" : "ghost"} onClick={() => setTab("bible")}>角色、场景与剧本</Button></nav>
      {tab === "shots" ? <StoryboardStage projectId={projectId} /> : <BibleStage projectId={projectId} />}
    </> : null}
  </div>;
}
