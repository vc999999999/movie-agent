import { useEffect, useState } from "react";
import {
  useConfirmBrief,
  useProject,
  useQuestions,
  useSubmitAnswers,
} from "../../api/queries";
import type { CreativeBrief, QuestionItem } from "../../api/types";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { useToast } from "../../components/Toast";
import { useInspector } from "../../app/App";
import { StatusBadge } from "../../components/StatusBadge";

function DecisionCard({
  question,
  selected,
  onSelect,
}: {
  question: QuestionItem;
  selected: string | undefined;
  onSelect: (field: string, answer: string | null) => void;
}) {
  return (
    <div className="card" style={{ padding: 18, display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <strong style={{ fontSize: 14 }}>{question.text}</strong>
        {question.blocking ? <StatusBadge tone="warning" label="需要决定" /> : null}
      </div>
      <p className="text-tertiary" style={{ fontSize: 12 }}>
        字段 <span className="mono">{question.field}</span>
        {question.affects.length > 0 ? ` · 影响：${question.affects.join("、")}` : ""}
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} role="radiogroup" aria-label={question.text}>
        {question.choices.map((choice) => {
          const isSelected = selected === choice;
          return (
            <button
              key={choice}
              type="button"
              role="radio"
              aria-checked={isSelected}
              className={`tag hover-lift ${isSelected ? "tag-accent" : ""}`}
              style={{ padding: "6px 14px", fontSize: 13 }}
              onClick={() => onSelect(question.field, choice)}
            >
              {choice}
            </button>
          );
        })}
        <button
          type="button"
          role="radio"
          aria-checked={selected === undefined}
          className={`tag hover-lift ${selected === undefined ? "tag-accent" : ""}`}
          style={{ padding: "6px 14px", fontSize: 13 }}
          onClick={() => onSelect(question.field, null)}
        >
          交给导演决定
        </button>
      </div>
    </div>
  );
}

const ASPECT_OPTIONS = ["16:9", "9:16", "1:1", "2.39:1"] as const;
const DIALOGUE_OPTIONS = [
  { value: "none", label: "无对白" },
  { value: "voiceover", label: "旁白" },
  { value: "dialogue", label: "对白" },
  { value: "mixed", label: "混合" },
] as const;

function BriefReview({ projectId, brief }: { projectId: string; brief: CreativeBrief }) {
  const [form, setForm] = useState<CreativeBrief>(brief);
  const confirmBrief = useConfirmBrief(projectId);
  const { toast } = useToast();

  useEffect(() => setForm(brief), [brief]);

  const set = <K extends keyof CreativeBrief>(key: K, value: CreativeBrief[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const field = (label: string, node: React.ReactNode) => (
    <label style={{ display: "grid", gap: 6, fontSize: 13 }}>
      <span className="text-secondary">{label}</span>
      {node}
    </label>
  );

  const submit = () => {
    if (confirmBrief.isPending) return;
    const payload: Record<string, unknown> = {
      title: form.title,
      logline: form.logline,
      duration_seconds: form.duration_seconds,
      aspect_ratio: form.aspect_ratio,
      dialogue_mode: form.dialogue_mode,
      visual_style: form.visual_style,
      protagonist: form.protagonist,
      protagonist_goal: form.protagonist_goal,
      conflict: form.conflict,
      ending: form.ending,
    };
    confirmBrief.mutate(payload, {
      onSuccess: () => toast("创作简报已确认，剧本与分镜已生成", "success"),
    });
  };

  return (
    <div className="card" style={{ padding: 22, display: "grid", gap: 16, maxWidth: 720 }}>
      <h2 className="display" style={{ fontSize: 20 }}>创作简报审阅</h2>
      <p className="text-secondary" style={{ fontSize: 13 }}>
        确认后 Agent 将锁定创作设定并生成剧本与分镜。上游修改会使下游产物失效。
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {field("标题", <input value={form.title ?? ""} onChange={(e) => set("title", e.target.value)} />)}
        {field(
          "时长（秒）",
          <input
            type="number"
            min={10}
            max={90}
            value={form.duration_seconds}
            onChange={(e) => set("duration_seconds", Number(e.target.value))}
          />,
        )}
        {field(
          "画幅",
          <select value={form.aspect_ratio} onChange={(e) => set("aspect_ratio", e.target.value as CreativeBrief["aspect_ratio"])}>
            {ASPECT_OPTIONS.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>,
        )}
        {field(
          "对白模式",
          <select value={form.dialogue_mode} onChange={(e) => set("dialogue_mode", e.target.value as CreativeBrief["dialogue_mode"])}>
            {DIALOGUE_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>,
        )}
      </div>
      {field("Logline", <textarea rows={2} value={form.logline} onChange={(e) => set("logline", e.target.value)} />)}
      {field("视觉风格", <input value={form.visual_style} onChange={(e) => set("visual_style", e.target.value)} />)}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {field("主角", <input value={form.protagonist} onChange={(e) => set("protagonist", e.target.value)} />)}
        {field("主角目标", <input value={form.protagonist_goal} onChange={(e) => set("protagonist_goal", e.target.value)} />)}
      </div>
      {field("核心冲突", <textarea rows={2} value={form.conflict} onChange={(e) => set("conflict", e.target.value)} />)}
      {field("结局", <input value={form.ending ?? ""} onChange={(e) => set("ending", e.target.value)} />)}

      {form.agent_assumptions.length > 0 ? (
        <div>
          <span className="text-tertiary" style={{ fontSize: 12 }}>Agent 默认假设</span>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, display: "grid", gap: 4 }}>
            {form.agent_assumptions.map((a) => (
              <li key={a} className="text-secondary" style={{ fontSize: 13 }}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {confirmBrief.isError ? (
        <ErrorNotice title="确认简报失败" impact="剧本与分镜尚未生成。" error={confirmBrief.error} />
      ) : null}

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button variant="primary" onClick={submit} disabled={confirmBrief.isPending}>
          {confirmBrief.isPending ? "正在生成剧本与分镜…" : "确认简报并生成剧本"}
        </Button>
      </div>
    </div>
  );
}

export function BriefStage({ projectId }: { projectId: string }) {
  const projectQuery = useProject(projectId);
  const status = projectQuery.data?.project.status;
  const isReview = status === "brief_review";
  const questionsQuery = useQuestions(isReview ? null : projectId);
  const submitAnswers = useSubmitAnswers(projectId);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const { toast } = useToast();

  const qResp = questionsQuery.data;

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>创意上下文</h3>
      {qResp ? (
        <>
          <div>
            <div className="text-tertiary" style={{ fontSize: 12, marginBottom: 6 }}>
              Brief 完成度 {Math.round(qResp.brief_completion * 100)}% · 第 {qResp.round} 轮
            </div>
            <div style={{ height: 4, borderRadius: 2, background: "rgb(255 255 255 / 8%)" }}>
              <div
                style={{
                  height: "100%",
                  width: `${Math.round(qResp.brief_completion * 100)}%`,
                  borderRadius: 2,
                  background: "var(--accent)",
                  transition: "width 240ms var(--spring)",
                }}
              />
            </div>
          </div>
          {qResp.assumptions.length > 0 ? (
            <div>
              <div className="text-tertiary" style={{ fontSize: 12, marginBottom: 6 }}>Agent 默认假设</div>
              <ul style={{ margin: 0, paddingLeft: 16, display: "grid", gap: 4 }}>
                {qResp.assumptions.map((a) => (
                  <li key={a} className="text-secondary" style={{ fontSize: 12 }}>{a}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : (
        <p className="text-tertiary" style={{ fontSize: 12 }}>审阅并确认创作设定后，可进入导演技法选择。</p>
      )}
    </div>,
    [qResp],
  );

  if (isReview && projectQuery.data?.project.brief) {
    return <BriefReview projectId={projectId} brief={projectQuery.data.project.brief} />;
  }

  const answeredCount = Object.keys(answers).length;

  const submit = () => {
    if (answeredCount === 0 || submitAnswers.isPending) return;
    submitAnswers.mutate(
      Object.entries(answers).map(([field, answer]) => ({ field, answer })),
      {
        onSuccess: (data) => {
          setAnswers({});
          if (data.status === "brief_review" || data.can_confirm) {
            toast("要素已完备，请审阅创作简报", "success");
          }
        },
      },
    );
  };

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 720 }}>
      <header>
        <h2 className="display" style={{ fontSize: 22 }}>导演需要你做几个决定</h2>
        <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
          每个选择都会改变后续的剧本与分镜。不确定的交给导演决定。
        </p>
      </header>

      {questionsQuery.isLoading ? (
        <p className="text-tertiary" aria-live="polite">正在分析问题…</p>
      ) : null}

      {questionsQuery.isError ? (
        <ErrorNotice title="无法获取反问" impact="请刷新重试。" error={questionsQuery.error} />
      ) : null}

      {qResp && qResp.questions.length === 0 ? (
        <div className="card" style={{ padding: 18 }}>
          <p className="text-secondary" style={{ fontSize: 13 }}>要素已基本完备，请等待进入简报审阅。</p>
        </div>
      ) : null}

      {qResp?.questions.map((q) => (
        <DecisionCard
          key={q.question_id}
          question={q}
          selected={answers[q.field]}
          onSelect={(field, answer) =>
            setAnswers((prev) => {
              const next = { ...prev };
              if (answer === null) delete next[field];
              else next[field] = answer;
              return next;
            })
          }
        />
      ))}

      {submitAnswers.isError ? (
        <ErrorNotice title="提交回答失败" impact="回答未保存，请重试。" error={submitAnswers.error} />
      ) : null}

      {qResp && qResp.questions.length > 0 ? (
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <Button variant="primary" onClick={submit} disabled={answeredCount === 0 || submitAnswers.isPending}>
            {submitAnswers.isPending ? "提交中…" : `提交 ${answeredCount} 个回答`}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
