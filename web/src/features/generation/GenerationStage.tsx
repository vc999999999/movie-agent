import { ProductionTools } from "../../components/ProductionTools";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, encodeSeg } from "../../api/client";
import { useCompilePackages, usePackages } from "../../api/queries";
import { navigateStage } from "../../app/stages";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { useInspector } from "../../app/App";

interface Delivery {
  status: "complete" | "partial";
  shot_count: number; workflow_count: number; ui_workflow_count: number; required_asset_count: number;
  workflows: { shot_id: string; workflow_id: string | null; reason: string | null; ui_file: string | null; api_file: string | null }[];
  dependencies: { workflow_id: string; name: string; min_vram_gb: number; required_models: string[]; required_nodes: string[] }[];
  assets: { filename: string; shot_id: string; positive_prompt: string; negative_prompt: string; width: number; height: number }[];
}
export function GenerationStage({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const packages = usePackages(projectId, true);
  const compile = useCompilePackages(projectId);
  const delivery = useQuery({ queryKey: ["delivery", projectId], queryFn: () => apiJson<Delivery>(`/api/projects/${encodeSeg(projectId)}/delivery`), retry: false });
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<Error | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const data = delivery.isError ? undefined : delivery.data;
  const busy = downloading || compile.isPending;
  useInspector(<div className="production-page"><h3>交付说明</h3><p className="text-secondary">ZIP 包包含项目制作资料，以及每个镜头的界面工作流与 API 文件。</p><p className="text-secondary">界面工作流可以拖入 ComfyUI。按依赖清单安装模型，准备首帧后再运行。</p><p className="text-tertiary">在线渲染与粗剪是可选步骤，不影响工作流交付。</p></div>, []);
  async function download() {
    setDownloading(true); setDownloadError(null); setDownloaded(false);
    try {
      const response = await fetch(`/api/projects/${encodeSeg(projectId)}/export`);
      if (!response.ok) { const body = await response.json(); throw new Error(body.detail ?? "下载失败"); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${projectId}_comfyui.zip`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
      setDownloaded(true);
    } catch (error) { setDownloadError(error instanceof Error ? error : new Error("下载失败")); }
    finally { setDownloading(false); }
  }
  async function recompile() {
    try { await compile.mutateAsync(); setDownloaded(false); await qc.invalidateQueries({ queryKey: ["delivery", projectId] }); }
    catch { /* Mutation error is rendered below. */ }
  }
  return <div className="production-page">
    <header className="production-heading"><div><p className="eyebrow">HANDOFF / 工作流交付</p><h1 className="display">把这场戏带进 ComfyUI</h1><p className="text-secondary">下载制作包，在你的设备上准备素材、运行镜头工作流。</p></div><Button onClick={() => navigateStage("storyboard")}>返回制作流程</Button></header>
    {delivery.isLoading ? <p role="status">正在整理交付清单…</p> : null}
    {delivery.isError ? <ErrorNotice title="制作包尚未就绪" error={delivery.error} actions={<Button onClick={() => void delivery.refetch()}>刷新清单</Button>} /> : null}
    {data ? <>
      <section className="delivery-hero">
        <div><span className="eyebrow">{data.status === "complete" ? "制作文件已生成" : "部分镜头尚未匹配"}</span><h2 className="display">{data.workflow_count} / {data.shot_count} 个镜头工作流</h2><p>{data.ui_workflow_count} 个可视化工作流 · {data.required_asset_count} 张首帧待准备</p><p className="text-secondary">含剧本、角色与场景设定、分镜、提示词、素材需求和依赖说明。</p></div>
        <div className="delivery-action"><Button variant="primary" onClick={() => void download()} disabled={busy}>{downloading ? "正在打包下载…" : data.status === "complete" ? "下载完整制作包 ZIP" : "下载现有制作资料 ZIP"}</Button><span className="text-tertiary">导出无需连接 ComfyUI 或等待视频渲染</span></div>
      </section>
      {downloaded ? <p role="status" className="text-accent">制作包已交给浏览器下载。解压后从 README.md 开始。</p> : null}
      <p className="delivery-note">文件已编译，尚未在你的 ComfyUI 环境渲染验证。请准备下方首帧素材并核对模型依赖。</p>
      <section className="production-page"><h2>镜头与工作流</h2>{data.workflows.map(item => {
        const prompt = packages.data?.prompt_packages.find(p => p.shot_id === item.shot_id);
        return <article className="delivery-shot" key={item.shot_id}><div className="delivery-shot-heading"><strong className="mono">{item.shot_id}</strong><span className="text-secondary">{item.workflow_id ?? "未匹配模板"}</span><span className="delivery-shot-links">{item.ui_file ? <a href={`/api/projects/${encodeSeg(projectId)}/workflow/${encodeSeg(item.shot_id)}?format=ui`} download>界面工作流</a> : null}{item.api_file ? <a href={`/api/projects/${encodeSeg(projectId)}/workflow/${encodeSeg(item.shot_id)}`} download>API JSON</a> : null}</span></div>{item.reason ? <p className="text-danger">{item.reason}</p> : null}{prompt ? <details><summary>查看提示词与参数 · {prompt.width}×{prompt.height} · {prompt.frame_count} 帧 / {prompt.fps} FPS</summary><pre>{prompt.positive_prompt}</pre><p className="text-secondary">负向提示词</p><pre>{prompt.negative_prompt}</pre></details> : null}</article>;
      })}</section>
      {data.assets.length > 0 ? <section className="production-page"><h2>首帧素材准备</h2><p className="text-secondary">按提示词生成或自行准备图片，保持角色外观一致；使用下列文件名放入 ComfyUI/input/。</p>{data.assets.map(asset => <details className="delivery-shot" key={asset.filename}><summary><span className="mono">{asset.filename}</span> · {asset.width}×{asset.height} · 待准备</summary><pre>{asset.positive_prompt}</pre></details>)}</section> : null}
      <section className="production-page"><h2>模型与节点依赖</h2>{data.dependencies.map(dep => <details className="delivery-shot" key={dep.workflow_id}><summary>{dep.name} · 参考显存 {dep.min_vram_gb} GB</summary><p>模型位置（相对于 ComfyUI/models/）</p><ul>{dep.required_models.map(model => <li className="mono" key={model}>{model}</li>)}</ul><p className="text-secondary">节点：{dep.required_nodes.join("、")}</p></details>)}</section>
    </> : null}
    {downloadError ? <ErrorNotice title="下载失败" error={downloadError} /> : null}
    {compile.isError ? <ErrorNotice title="重新编译失败" error={compile.error} /> : null}
    <ProductionTools projectId={projectId} />
    <footer className="production-heading"><Button onClick={() => void recompile()} disabled={busy}>{compile.isPending ? "正在编译…" : "重新编译工作流"}</Button><Button variant="ghost" onClick={() => navigateStage("render")}>可选：在线渲染与粗剪</Button></footer>
  </div>;
}
