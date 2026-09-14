import { ProductionTools } from "../../components/ProductionTools";
import { useMemo, useState, useEffect } from "react";
import { encodeSeg, outputUrl } from "../../api/client";
import { useCreateRoughCut, usePackages, useProject, useShots } from "../../api/queries";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { useToast } from "../../components/Toast";
import { useInspector } from "../../app/App";

// Minimal safe Markdown renderer: headings, bold, lists, paragraphs. No raw HTML.
function Markdown({ source }: { source: string }) {
  const blocks = useMemo(() => {
    const lines = source.split(/\r?\n/);
    const out: React.ReactNode[] = [];
    let list: string[] = [];
    const flushList = (key: string) => {
      if (list.length > 0) {
        out.push(
          <ul key={key} style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 4 }}>
            {list.map((item, i) => (
              <li key={i} style={{ fontSize: 13 }}>{renderInline(item)}</li>
            ))}
          </ul>,
        );
        list = [];
      }
    };
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      const heading = trimmed.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        flushList(`l${idx}`);
        const level = heading[1].length;
        out.push(
          <div key={idx} style={{ fontSize: level <= 2 ? 16 : 14, fontWeight: 600, marginTop: 8 }}>
            {renderInline(heading[2])}
          </div>,
        );
        return;
      }
      const item = trimmed.match(/^[-*]\s+(.*)$/);
      if (item) {
        list.push(item[1]);
        return;
      }
      flushList(`l${idx}`);
      if (trimmed) {
        out.push(
          <p key={idx} style={{ fontSize: 13, lineHeight: 1.7 }} className="text-secondary">
            {renderInline(trimmed)}
          </p>,
        );
      }
    });
    flushList("end");
    return out;
  }, [source]);
  return <div style={{ display: "grid", gap: 8 }}>{blocks}</div>;
}

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="mono" style={{ fontSize: 12, background: "rgb(0 0 0 / 30%)", borderRadius: 4, padding: "1px 5px" }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

export function PreviewStage({ projectId }: { projectId: string }) {
  const projectQuery = useProject(projectId);
  const status = projectQuery.data?.project.status;
  const shotsQuery = useShots(projectId, true);
  const packagesQuery = usePackages(projectId, true);
  const createRoughCut = useCreateRoughCut(projectId);
  const [roughCutReady, setRoughCutReady] = useState(status === "completed");
  useEffect(() => setRoughCutReady(status === "completed"), [status, projectQuery.dataUpdatedAt]);
  const { toast } = useToast();

  const shots = shotsQuery.data?.shots ?? [];
  const report = packagesQuery.data?.production_report ?? "";
  const failed = status === "failed";

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>粗剪上下文</h3>
      <p className="text-secondary" style={{ fontSize: 12 }}>
        {shots.length} 个镜头 · 总时长{" "}
        <span className="mono">{shotsQuery.data ? shotsQuery.data.total_duration.toFixed(1) : "-"}s</span>
      </p>
      <p className="text-tertiary" style={{ fontSize: 12 }}>
        在作品制作面板编辑声音和字幕，合成后核对实际成片。
      </p>
    </div>,
    [shots.length, shotsQuery.data],
  );

  const makeRoughCut = () => {
    if (createRoughCut.isPending) return;
    createRoughCut.mutate(undefined, {
      onSuccess: () => {
        setRoughCutReady(true);
        toast("粗剪短片合成完毕", "success");
      },
    });
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <header>
        <h2 className="display" style={{ fontSize: 22 }}>粗剪预览</h2>
        <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
          播放合成后的粗剪短片，核对镜头顺序与时长。
        </p>
      </header>
      <ProductionTools projectId={projectId} />

      {failed ? (
        <ErrorNotice
          title="项目处于失败状态"
          impact="部分镜头可能未渲染成功。可返回生成工作台查看失败原因并重试。"
          actions={
            <Button variant="secondary" size="sm" onClick={makeRoughCut} disabled={createRoughCut.isPending}>
              尝试重新合成粗剪
            </Button>
          }
        />
      ) : null}

      <section className="card" style={{ padding: 20, display: "grid", gap: 14 }}>
        {roughCutReady ? (
          <>
            <video
              key={String(roughCutReady)}
              src={outputUrl(projectId, "rough_cut.mp4")}
              controls
              preload="metadata"
              style={{ width: "100%", maxWidth: 960, borderRadius: 12, border: "1px solid var(--line)", background: "#000" }}
            />
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <a
                className="tag tag-accent hover-lift"
                href={`/api/projects/${encodeSeg(projectId)}/rough_cut/download`}
                download
              >
                下载粗剪 MP4
              </a>
              <Button variant="ghost" size="sm" onClick={makeRoughCut} disabled={createRoughCut.isPending}>
                {createRoughCut.isPending ? "重新合成中…" : "重新合成"}
              </Button>
            </div>
          </>
        ) : (
          <div style={{ display: "grid", gap: 10, maxWidth: 460 }}>
            <p className="text-secondary" style={{ fontSize: 13 }}>
              尚未合成粗剪。确认所有需要的镜头已渲染成功后，调用 FFmpeg 合成。
            </p>
            <div>
              <Button variant="primary" onClick={makeRoughCut} disabled={createRoughCut.isPending}>
                {createRoughCut.isPending ? "正在合成粗剪…" : "合成粗剪短片"}
              </Button>
            </div>
          </div>
        )}
        {createRoughCut.isError ? (
          <ErrorNotice
            title="粗剪合成失败"
            impact="已渲染的镜头不受影响。可返回生成工作台检查缺失镜头。"
            error={createRoughCut.error}
          />
        ) : null}
      </section>

      {shots.length > 0 ? (
        <section className="card" style={{ padding: 18, display: "grid", gap: 8 }} aria-label="镜头清单">
          <h3 style={{ fontSize: 15 }}>镜头清单</h3>
          {shots.map((s) => (
            <div key={s.shot_id} style={{ display: "flex", gap: 12, alignItems: "baseline", fontSize: 13 }}>
              <span className="mono text-tertiary" style={{ fontSize: 11 }}>{String(s.order).padStart(2, "0")}</span>
              <span className="mono" style={{ fontSize: 12 }}>{s.shot_id}</span>
              <span className="tag mono" style={{ fontSize: 11 }}>{s.duration_seconds}s</span>
              <span className="text-secondary" style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {s.action}
              </span>
            </div>
          ))}
        </section>
      ) : null}

      {report ? (
        <section className="card" style={{ padding: 20, display: "grid", gap: 10, maxWidth: 720 }} aria-label="制作报告">
          <h3 className="display" style={{ fontSize: 16 }}>制作报告</h3>
          <Markdown source={report} />
        </section>
      ) : null}
    </div>
  );
}
