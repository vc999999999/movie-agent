import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, encodeSeg, outputUrl } from "../api/client";
import { Button } from "./Button";

type Asset = { id: string; purpose: "reference" | "voice" | "music" | "effect"; source: string; license_note: string; rights: string };
type Clip = { asset_id: string; role: string; start: number; end: number; offset: number; volume: number };
type Sub = { start: number; end: number; text: string };
type Timeline = { audio: Clip[]; subtitles: Sub[]; missing_voice_shots: string[] };
type Frame = { shot_id: string; character_ids: string[]; location_id: string; frames: string[] };
type Review = { content: { simulation?: boolean; passed: boolean; issues: { evidence: string; instruction: string; shot_ids: string[]; scene_ids: string[] }[] } };

export function ProductionTools({ projectId }: { projectId: string }) {
  const base = `/api/projects/${encodeSeg(projectId)}`;
  const qc = useQueryClient();
  const assets = useQuery({ queryKey: ["assets", projectId], queryFn: () => apiJson<Asset[]>(`${base}/assets`) });
  const timeline = useQuery({ queryKey: ["timeline", projectId], queryFn: () => apiJson<Timeline>(`${base}/timeline`) });
  const frames = useQuery({ queryKey: ["comparison", projectId], queryFn: () => apiJson<Frame[]>(`${base}/comparison`) });
  const reviews = useQuery({ queryKey: ["quality", projectId], queryFn: () => apiJson<{ reviews: Review[] }>(`${base}/quality`) });
  const shots = useQuery({ queryKey: ["production-shots", projectId], queryFn: () => apiJson<{ shots: { shot_id: string; action: string }[] }>(`${base}/shots`) });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [purpose, setPurpose] = useState<Asset["purpose"]>("reference");
  const [source, setSource] = useState("");
  const [license, setLicense] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [projectDefault, setProjectDefault] = useState(false);
  const [selected, setSelected] = useState("");
  const [selectedShot, setSelectedShot] = useState("");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(3);
  const [offset, setOffset] = useState(0);
  const [volume, setVolume] = useState(1);
  const [note, setNote] = useState("");
  const [subtitleDraft, setSubtitleDraft] = useState<Sub[] | null>(null);
  const [constraintText, setConstraintText] = useState("");
  const [remoteId, setRemoteId] = useState("");
  const [remoteEvidence, setRemoteEvidence] = useState("");
  const [notSubmitted, setNotSubmitted] = useState(false);
  const pending = useQuery({ queryKey: ["production-pending", projectId], queryFn: () => apiJson<{ pending_runs: { run_id: string; shot_id: string; task_id?: string; error?: string }[] }>(`${base}/auto_pipeline`), refetchInterval: 10000 });

  async function act(work: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage("");
    try { await work(); setMessage(success); await qc.invalidateQueries(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  async function upload() {
    if (!file) throw new Error("请选择素材文件");
    const metadata = { purpose, project_default: purpose === "reference" && projectDefault, source, license_note: license, rights: confirmed ? "confirmed" : "pending" };
    const response = await fetch(`${base}/assets?metadata=${encodeURIComponent(JSON.stringify(metadata))}`, { method: "POST", body: file });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? "上传失败");
  }
  async function save(audio: Clip[], subtitles: Sub[]) {
    await apiJson(`${base}/timeline`, { method: "PUT", body: { audio, subtitles } });
  }
  async function download(competition: boolean) {
    const response = await fetch(`${base}/evidence/export?competition=${competition}`, { method: "POST" });
    if (!response.ok) { const body = await response.json(); throw new Error(body.detail ?? "导出失败"); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = `${projectId}-evidence.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const current = timeline.data ?? { audio: [], subtitles: [], missing_voice_shots: [] };
  const latest = reviews.data?.reviews.slice(-1)[0]?.content;
  const available = assets.data ?? [];
  const chosen = available.find(a => a.id === selected);
  const layout = { display: "grid", gap: 12 };

  return <section className="card" style={{ padding: 20, ...layout }} aria-label="作品制作与验收">
    <h3>作品制作与验收</h3>
    <p className="text-secondary">检查文字与画面，绑定参考素材，编辑声音和字幕，再导出作品证据。</p>
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <Button disabled={busy} onClick={() => void act(() => apiJson(`${base}/auto_pipeline`, { method: "POST" }), "已启动，将复用有效镜头")}>恢复生成</Button>
      <Button disabled={busy} onClick={() => void act(() => apiJson(`${base}/quality/repair`, { method: "POST" }), "质检与修正完成")}>质检并修正</Button>
      <Button disabled={busy} onClick={() => void act(() => apiJson(`${base}/comparison`, { method: "POST" }), "画面对照已更新")}>生成画面对照</Button>
      <Button disabled={busy} onClick={() => void act(() => download(false), "预览证据已下载")}>下载预览证据</Button>
      <Button disabled={busy} onClick={() => void act(() => download(true), "参赛作品包已下载")}>导出参赛作品包</Button>
    </div>
    {message && <p role="status" style={{ whiteSpace: "pre-wrap" }}>{message}</p>}
    {latest && <div><strong>最近文本质检：{latest.passed ? "通过" : "需修订"}{latest.simulation ? "（仿真，仅验证流程）" : ""}</strong>{latest.issues.map((issue, i) => <p key={i}>{[...issue.scene_ids, ...issue.shot_ids].join("、")}：{issue.evidence} → {issue.instruction}</p>)}</div>}
    {(pending.data?.pending_runs ?? []).length > 0 && <details><summary>核实远端提交</summary><p>已知远端任务会在恢复时继续查询。没有任务 ID 的记录需要先在生成服务核实，避免重复计费。</p><label>查到的远端任务 ID<input value={remoteId} onChange={e => setRemoteId(e.target.value)} disabled={notSubmitted} /></label><label><input type="checkbox" checked={notSubmitted} onChange={e => setNotSubmitted(e.target.checked)} />已核实远端没有接受此次提交</label><label>核实依据<input value={remoteEvidence} onChange={e => setRemoteEvidence(e.target.value)} /></label>{pending.data?.pending_runs.map(run => <div key={run.run_id}>{run.shot_id} · {run.error ?? "远端任务进行中"} <Button disabled={busy || !remoteEvidence || (!notSubmitted && !remoteId)} onClick={() => void act(() => apiJson(`${base}/renders/${run.run_id}/reconcile`, { method: "POST", body: { evidence: remoteEvidence, task_id: notSubmitted ? null : remoteId, not_submitted: notSubmitted } }), "核实结果已记录，可恢复生成")}>记录核实结果</Button></div>)}</details>}
    <details><summary>澄清或调整明确要求</summary><div style={layout}>
      <label>用一句话重新说明时长、画幅、人物数量与对白要求<input value={constraintText} onChange={e => setConstraintText(e.target.value)} placeholder="30秒，竖屏，两名角色，无对白" /></label>
      <Button disabled={busy || !constraintText.trim()} onClick={() => void act(() => apiJson(`${base}/constraints`, { method: "PUT", body: { text: constraintText } }), "明确要求已更新，后续内容需要重新生成")}>更新明确要求</Button>
    </div></details>
    <details><summary>素材与授权</summary><div style={layout}>
      <label>素材文件<input type="file" accept="image/png,image/jpeg,audio/*" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      <label>用途<select value={purpose} onChange={e => setPurpose(e.target.value as Asset["purpose"])}><option value="reference">参考首帧</option><option value="voice">对白／旁白</option><option value="music">音乐</option><option value="effect">音效</option></select></label>
      {purpose === "reference" && <label><input type="checkbox" checked={projectDefault} onChange={e => setProjectDefault(e.target.checked)} />作为未单独绑定镜头的全片默认首帧</label>}
      <label>来源<input value={source} onChange={e => setSource(e.target.value)} placeholder="原创录制、素材来源链接等" /></label>
      <label>授权依据<input value={license} onChange={e => setLicense(e.target.value)} /></label>
      <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已确认这份素材的使用权利</label>
      <Button disabled={busy || !file || !source} onClick={() => void act(upload, "素材已登记")}>上传素材</Button>
      {available.map(a => <div key={a.id}><span>{a.id} · {a.purpose} · {a.source} · {a.rights === "confirmed" ? "已确认" : "授权待审"}</span>{a.rights !== "confirmed" && <Button disabled={busy || !license.trim()} size="sm" onClick={() => void act(() => apiJson(`${base}/assets/${a.id}`, { method: "PATCH", body: { rights: "confirmed", license_note: license } }), "授权依据已记录")}>按所填依据确认</Button>}</div>)}
      <label>选择素材<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">请选择</option>{available.map(a => <option key={a.id} value={a.id}>{a.id} · {a.purpose}</option>)}</select></label>
      <label>目标镜头<select value={selectedShot} onChange={e => setSelectedShot(e.target.value)}><option value="">请选择镜头</option>{shots.data?.shots.map(s => <option key={s.shot_id} value={s.shot_id}>{s.shot_id} · {s.action.slice(0, 35)}</option>)}</select></label>
      <Button disabled={busy || chosen?.purpose !== "reference" || !selectedShot} onClick={() => void act(() => apiJson(`${base}/shots/${selectedShot}`, { method: "PATCH", body: { updates: { reference_asset_ids: [selected] } } }), "首帧已绑定，恢复生成将重新编译")}>绑定为镜头首帧</Button>
      <p>同一角色可在不同镜头复用已登记的参考图。当前模板每镜头支持一张首帧。</p>
    </div></details>
    <details><summary>声音时间线与字幕</summary><div style={layout}>
      {current.missing_voice_shots.length > 0 && <p>配音待补齐：{current.missing_voice_shots.join("、")}。字幕不代表配音已完成。</p>}
      <label>音频素材<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">请选择</option>{available.filter(a => a.purpose !== "reference").map(a => <option key={a.id} value={a.id}>{a.id} · {a.purpose}</option>)}</select></label>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>{([['开始秒', start, setStart], ['结束秒', end, setEnd], ['素材偏移秒', offset, setOffset], ['音量 0–2', volume, setVolume]] as const).map(([label, value, setter]) => <label key={label}>{label}<input type="number" min="0" step="0.1" value={value} onChange={e => setter(Number(e.target.value))} style={{ width: 100 }} /></label>)}</div>
      <Button disabled={busy || !chosen || chosen.purpose === "reference"} onClick={() => void act(() => save([...current.audio, { asset_id: selected, role: chosen!.purpose, start, end, offset, volume }], current.subtitles), "音频片段已加入")}>加入声音时间线</Button>
      {current.audio.map((c, i) => <div key={i}>{c.role} · {c.start}–{c.end}s · 音量 {c.volume} <Button size="sm" disabled={busy} onClick={() => void act(() => save(current.audio.filter((_, index) => index !== i), current.subtitles), "片段已移除")}>移除片段 {i + 1}</Button></div>)}
      {(subtitleDraft ?? current.subtitles).map((s, i) => <div key={i} style={{ display: "flex", gap: 8 }}><label>字幕 {i + 1} 开始<input type="number" step="0.1" value={s.start} onChange={e => setSubtitleDraft((subtitleDraft ?? current.subtitles).map((x, j) => j === i ? { ...x, start: Number(e.target.value) } : x))} style={{ width: 85 }} /></label><label>结束<input type="number" step="0.1" value={s.end} onChange={e => setSubtitleDraft((subtitleDraft ?? current.subtitles).map((x, j) => j === i ? { ...x, end: Number(e.target.value) } : x))} style={{ width: 85 }} /></label><label style={{ flex: 1 }}>字幕文字<input value={s.text} onChange={e => setSubtitleDraft((subtitleDraft ?? current.subtitles).map((x, j) => j === i ? { ...x, text: e.target.value } : x))} /></label></div>)}
      <Button onClick={() => setSubtitleDraft([...(subtitleDraft ?? current.subtitles), { start, end, text: "请输入字幕" }])}>添加字幕</Button>
      <Button disabled={busy || subtitleDraft === null} onClick={() => void act(async () => { await save(current.audio, subtitleDraft!); setSubtitleDraft(null); }, "字幕已保存")}>保存字幕</Button>
      <Button disabled={busy} onClick={() => void act(() => apiJson(`${base}/rough_cut`, { method: "POST" }), "成片已更新")}>按时间线合成</Button>
    </div></details>
    {(frames.data ?? []).map(f => <div key={f.shot_id} style={layout}><strong>{f.shot_id} · {f.character_ids.join("、")} · {f.location_id}</strong><div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{f.frames.map((name, i) => <img key={name} src={outputUrl(projectId, name)} alt={`${f.shot_id} ${["起幅", "中段", "落幅"][i]}`} style={{ width: "30%", minWidth: 140 }} />)}</div><label>画面问题<input value={selectedShot === f.shot_id ? note : ""} onChange={e => { setSelectedShot(f.shot_id); setNote(e.target.value); }} /></label><div><Button disabled={busy || selectedShot !== f.shot_id || !note.trim()} onClick={() => void act(() => apiJson(`${base}/shots/${f.shot_id}/feedback`, { method: "POST", body: { note } }), "问题已记录")}>记录问题</Button> <Button disabled={busy} onClick={() => void act(() => apiJson(`/api/shots/${f.shot_id}/render`, { method: "POST", body: { project_id: projectId, force: true } }), "镜头已重做，请刷新画面对照")}>重做此镜头</Button></div></div>)}
  </section>;
}
