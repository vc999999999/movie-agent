import { DemoNotice } from "../../components/DemoNotice";
import { useState } from "react";
import { useCreateProject, useProjectList } from "../../api/queries";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { useToast } from "../../components/Toast";

const EXAMPLES = [
  "雨夜，一名侦探在空旷的火车站等待一个永远不会来的证人，悬疑预告片",
  "一位宇航员在太空站收到女儿十年前发来的语音，亲情科幻短片",
  "小城面馆老板在拆迁前夜决定做最后一碗面，温情现实主义",
];

const QUICK_CHIPS = ["45 秒", "16:9", "悬疑", "写实电影感"];

interface BriefHomeProps {
  onCreated: (projectId: string) => void;
  onOpen: (projectId: string) => void;
}

export function BriefHome({ onCreated, onOpen }: BriefHomeProps) {
  const [text, setText] = useState("");
  const createProject = useCreateProject();
  const projectList = useProjectList();
  const { toast } = useToast();

  const submit = () => {
    const source = text.trim();
    if (!source || createProject.isPending) return;
    createProject.mutate(
      { source_text: source },
      {
        onSuccess: (data) => {
          toast("项目已创建", "success");
          onCreated(data.project.id);
        },
      },
    );
  };

  const projects = Array.isArray(projectList.data) ? projectList.data : [];

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "72px 24px 64px", display: "grid", gap: 32 }}>
      <div style={{ textAlign: "center", display: "grid", gap: 12 }}>
        <DemoNotice />
        <h1 className="display" style={{ fontSize: 34, fontWeight: 600 }}>
          你脑海里的第一场戏是什么？
        </h1>
        <p className="text-secondary" style={{ fontSize: 15 }}>
          输入剧情或场景，拆解需求、选择导演模板，生成可交给 ComfyUI 使用的完整制作包。
        </p>
      </div>

      <div className="card" style={{ padding: 20, display: "grid", gap: 14 }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="例如：一个男人在雨夜的火车站等待十年未归的女儿……"
          style={{ resize: "vertical", minHeight: 110, fontSize: 15, lineHeight: 1.6 }}
          aria-label="电影创意输入"
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {QUICK_CHIPS.map((chip) => (
            <button
              key={chip}
              type="button"
              className="tag hover-lift"
              onClick={() => setText((t) => (t.trim() ? `${t.trim()}，${chip}` : chip))}
            >
              {chip}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <Button variant="primary" onClick={submit} disabled={!text.trim() || createProject.isPending}>
            {createProject.isPending ? "正在分析要素与规划…" : "拆解剧情"}
          </Button>
        </div>
        {createProject.isError ? (
          <ErrorNotice
            title="创建项目失败"
            impact="创意尚未保存，请重试。"
            error={createProject.error}
          />
        ) : null}
      </div>

      <section aria-label="剧情示例">
        <h2 className="text-tertiary" style={{ fontSize: 13, fontWeight: 500, marginBottom: 10 }}>试试这些剧情</h2>
        <div style={{ display: "grid", gap: 8 }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              className="card hover-lift"
              style={{ padding: "12px 16px", textAlign: "left", color: "var(--text-secondary)", fontSize: 13 }}
              onClick={() => setText(ex)}
            >
              {ex}
            </button>
          ))}
        </div>
      </section>

      {projects.length > 0 ? (
        <section aria-label="已有项目">
          <h2 className="text-tertiary" style={{ fontSize: 13, fontWeight: 500, marginBottom: 10 }}>继续之前的项目</h2>
          <div style={{ display: "grid", gap: 8 }}>
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                className="card hover-lift"
                style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 12, textAlign: "left" }}
                onClick={() => onOpen(p.id)}
              >
                <span className="mono text-tertiary" style={{ fontSize: 12 }}>{p.id}</span>
                <span style={{ fontSize: 14 }}>{p.title || "未命名项目"}</span>
                <span style={{ flex: 1 }} />
                <span className="tag">{p.status}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
