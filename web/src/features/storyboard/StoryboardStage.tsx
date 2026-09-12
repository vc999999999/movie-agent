import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useConfirmShots, useProject, useShots, useUpdateShot } from "../../api/queries";
import type { ContinuityIssue, GrammarIssue, ShotSize, ShotSpec } from "../../api/types";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { StageFooter } from "../../components/StageFooter";
import { StatusBadge } from "../../components/StatusBadge";
import { useNextStage } from "../../components/nextStage";
import { useToast } from "../../components/Toast";
import { useAiWait } from "../../components/useAiWait";
import { useInspector } from "../../app/App";

const SHOT_SIZES: ShotSize[] = ["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"];

interface UnifiedIssue {
  key: string;
  source: "连续性" | "导演语法" | "名导技法";
  severity: "warning" | "error";
  shotIds: string[];
  message: string;
  fix: string;
  field?: string;
}

function unifyIssues(
  continuity: ContinuityIssue[],
  grammar: GrammarIssue[],
  auteur: GrammarIssue[],
): UnifiedIssue[] {
  return [
    ...continuity.map((i, n) => ({
      key: `c${n}`,
      source: "连续性" as const,
      severity: i.severity,
      shotIds: i.shot_ids,
      message: i.explanation,
      fix: i.suggested_fix,
      field: i.field,
    })),
    ...grammar.map((i, n) => ({
      key: `g${n}`,
      source: "导演语法" as const,
      severity: i.severity,
      shotIds: i.shot_ids,
      message: `[${i.code}] ${i.message}`,
      fix: i.suggested_fix,
    })),
    ...auteur.map((i, n) => ({
      key: `a${n}`,
      source: "名导技法" as const,
      severity: i.severity,
      shotIds: i.shot_ids,
      message: `[${i.code}] ${i.message}`,
      fix: i.suggested_fix,
    })),
  ];
}

function FilmStrip({
  shots,
  selectedId,
  issueShotIds,
  onSelect,
}: {
  shots: ShotSpec[];
  selectedId: string | null;
  issueShotIds: Map<string, "warning" | "error">;
  onSelect: (id: string) => void;
}) {
  const total = shots.reduce((sum, s) => sum + s.duration_seconds, 0);
  if (total <= 0) return null;
  return (
    <div
      role="listbox"
      aria-label="时长比例胶片带"
      style={{ display: "flex", gap: 3, height: 44 }}
    >
      {shots.map((s) => {
        const isSelected = s.shot_id === selectedId;
        const issue = issueShotIds.get(s.shot_id);
        return (
          <button
            key={s.shot_id}
            type="button"
            role="option"
            aria-selected={isSelected}
            title={`${s.shot_id} · ${s.duration_seconds}s · ${s.shot_size}`}
            onClick={() => onSelect(s.shot_id)}
            className="mono"
            style={{
              flex: `${s.duration_seconds} 1 0`,
              minWidth: 28,
              borderRadius: 6,
              border: `1px solid ${isSelected ? "var(--accent)" : "var(--line)"}`,
              background: isSelected
                ? "var(--accent-tint)"
                : issue === "error"
                  ? "rgb(255 69 58 / 14%)"
                  : issue === "warning"
                    ? "rgb(255 214 10 / 10%)"
                    : "var(--canvas-raised)",
              color: isSelected ? "var(--accent-soft)" : "var(--text-tertiary)",
              fontSize: 10,
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
              padding: "0 4px",
              transition: "background 120ms var(--spring), border-color 120ms var(--spring)",
            }}
          >
            {s.shot_id.replace(/^S\d+_/, "")}
          </button>
        );
      })}
    </div>
  );
}

function ShotCard({
  shot,
  selected,
  issue,
  onSelect,
}: {
  shot: ShotSpec;
  selected: boolean;
  issue: "warning" | "error" | undefined;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className="card hover-lift"
      onClick={onSelect}
      aria-pressed={selected}
      style={{
        padding: 16,
        textAlign: "left",
        display: "grid",
        gap: 10,
        borderColor: selected
          ? "rgb(200 169 107 / 55%)"
          : issue === "error"
            ? "rgb(255 69 58 / 45%)"
            : issue === "warning"
              ? "rgb(255 214 10 / 35%)"
              : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{shot.shot_id}</span>
        <span className="tag mono" style={{ fontSize: 11 }}>{shot.duration_seconds}s</span>
        <span className="tag" style={{ fontSize: 11 }}>{shot.shot_size}</span>
        <span className="tag" style={{ fontSize: 11 }}>{shot.generation_mode}</span>
        <span style={{ flex: 1 }} />
        {issue === "error" ? <StatusBadge tone="danger" label="错误" /> : null}
        {issue === "warning" ? <StatusBadge tone="warning" label="警告" /> : null}
      </div>
      <div style={{ fontSize: 13, display: "grid", gap: 4 }}>
        <span><span className="text-tertiary">起幅 </span>{shot.start_frame}</span>
        <span><span className="text-secondary">主动作 </span>{shot.action}</span>
        <span><span className="text-tertiary">落幅 </span>{shot.end_frame}</span>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {shot.shot_function ? <span className="tag" style={{ fontSize: 11 }}>{shot.shot_function}</span> : null}
        {shot.technique_ids.map((t) => (
          <span key={t} className="tag tag-accent" style={{ fontSize: 11 }}>{t}</span>
        ))}
      </div>
    </button>
  );
}

function ShotEditDrawer({
  projectId,
  shot,
  onClose,
}: {
  projectId: string;
  shot: ShotSpec;
  onClose: () => void;
}) {
  const updateShot = useUpdateShot(projectId);
  const { toast } = useToast();
  const [form, setForm] = useState({
    duration_seconds: shot.duration_seconds,
    shot_size: shot.shot_size,
    start_frame: shot.start_frame,
    action: shot.action,
    end_frame: shot.end_frame,
    camera_angle: shot.camera_angle,
    camera_movement: shot.camera_movement,
    lighting: shot.lighting,
    mood: shot.mood,
    voiceover: shot.voiceover ?? "",
  });

  const dirty = JSON.stringify(form) !== JSON.stringify({
    duration_seconds: shot.duration_seconds,
    shot_size: shot.shot_size,
    start_frame: shot.start_frame,
    action: shot.action,
    end_frame: shot.end_frame,
    camera_angle: shot.camera_angle,
    camera_movement: shot.camera_movement,
    lighting: shot.lighting,
    mood: shot.mood,
    voiceover: shot.voiceover ?? "",
  });

  const save = () => {
    if (updateShot.isPending) return;
    const updates: Record<string, unknown> = { ...form };
    if (!form.voiceover) updates.voiceover = null;
    updateShot.mutate(
      { shot_id: shot.shot_id, updates },
      {
        onSuccess: () => {
          toast("镜头已保存，Prompt 与工作流已标记失效", "success");
          onClose();
        },
      },
    );
  };

  const field = (label: string, node: React.ReactNode) => (
    <label style={{ display: "grid", gap: 5, fontSize: 13 }}>
      <span className="text-secondary">{label}</span>
      {node}
    </label>
  );

  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="glass-strong"
      style={{
        position: "fixed",
        top: "var(--topbar-h)",
        right: 0,
        bottom: 0,
        width: 420,
        maxWidth: "92vw",
        zIndex: 70,
        padding: 22,
        overflowY: "auto",
        display: "grid",
        gap: 14,
        alignContent: "start",
      }}
      role="dialog"
      aria-label={`编辑镜头 ${shot.shot_id}`}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h3 className="mono" style={{ fontSize: 15 }}>{shot.shot_id}</h3>
        <span style={{ flex: 1 }} />
        <button type="button" className="tag hover-lift" onClick={onClose}>关闭</button>
      </div>
      <p className="text-tertiary" style={{ fontSize: 12 }}>
        保存后此镜头的 Prompt、工作流与粗剪将失效，需要重新编译与渲染。
      </p>
      {field(
        "时长（秒，1-12）",
        <input
          type="number"
          min={1}
          max={12}
          step={0.1}
          value={form.duration_seconds}
          onChange={(e) => setForm((f) => ({ ...f, duration_seconds: Number(e.target.value) }))}
        />,
      )}
      {field(
        "景别",
        <select
          value={form.shot_size}
          onChange={(e) => setForm((f) => ({ ...f, shot_size: e.target.value as ShotSize }))}
        >
          {SHOT_SIZES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>,
      )}
      {field("起幅", <textarea rows={2} value={form.start_frame} onChange={(e) => setForm((f) => ({ ...f, start_frame: e.target.value }))} />)}
      {field("主动作", <textarea rows={2} value={form.action} onChange={(e) => setForm((f) => ({ ...f, action: e.target.value }))} />)}
      {field("落幅", <textarea rows={2} value={form.end_frame} onChange={(e) => setForm((f) => ({ ...f, end_frame: e.target.value }))} />)}
      {field("摄影角度", <input value={form.camera_angle} onChange={(e) => setForm((f) => ({ ...f, camera_angle: e.target.value }))} />)}
      {field("运镜", <input value={form.camera_movement} onChange={(e) => setForm((f) => ({ ...f, camera_movement: e.target.value }))} />)}
      {field("光影", <input value={form.lighting} onChange={(e) => setForm((f) => ({ ...f, lighting: e.target.value }))} />)}
      {field("情绪", <input value={form.mood} onChange={(e) => setForm((f) => ({ ...f, mood: e.target.value }))} />)}
      {field("旁白", <textarea rows={2} value={form.voiceover} onChange={(e) => setForm((f) => ({ ...f, voiceover: e.target.value }))} />)}

      {updateShot.isError ? (
        <ErrorNotice title="保存镜头失败" impact="修改未生效。" error={updateShot.error} />
      ) : null}

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
        <Button variant="ghost" onClick={onClose}>取消</Button>
        <Button variant="primary" onClick={save} disabled={!dirty || updateShot.isPending}>
          {updateShot.isPending ? "保存中…" : "保存修改"}
        </Button>
      </div>
    </motion.div>
  );
}

export function StoryboardStage({ projectId }: { projectId: string }) {
  const shotsQuery = useShots(projectId, true);
  const confirmShots = useConfirmShots(projectId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const { toast } = useToast();
  const onNextStage = useNextStage("storyboard");
  const { withWait } = useAiWait();
  const projectQuery = useProject(projectId);
  const confirmed = projectQuery.data
    ? ["package_ready", "rendering", "completed", "failed"].includes(projectQuery.data.project.status)
    : false;

  const data = shotsQuery.data ?? null;
  const shots = useMemo(() => data?.shots ?? [], [data]);
  const issues = useMemo(
    () => (data ? unifyIssues(data.continuity_issues, data.grammar_issues, data.auteur_issues) : []),
    [data],
  );
  const issueShotIds = useMemo(() => {
    const map = new Map<string, "warning" | "error">();
    for (const issue of issues) {
      for (const id of issue.shotIds) {
        if (issue.severity === "error" || !map.has(id)) map.set(id, issue.severity);
      }
    }
    return map;
  }, [issues]);
  const errorCount = issues.filter((i) => i.severity === "error").length;

  const selectedShot = shots.find((s) => s.shot_id === selectedId) ?? null;

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>镜头检查器</h3>
      {selectedShot ? (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="mono" style={{ fontSize: 14, fontWeight: 600 }}>{selectedShot.shot_id}</span>
            <span className="tag mono" style={{ fontSize: 11 }}>{selectedShot.scene_id}</span>
          </div>
          <div style={{ display: "grid", gap: 8, fontSize: 12 }} className="text-secondary">
            <p><span className="text-tertiary">叙事目的：</span>{selectedShot.narrative_purpose}</p>
            {selectedShot.information_revealed ? <p><span className="text-tertiary">揭示：</span>{selectedShot.information_revealed}</p> : null}
            {selectedShot.information_withheld ? <p><span className="text-tertiary">保留：</span>{selectedShot.information_withheld}</p> : null}
            <p><span className="text-tertiary">构图：</span>{selectedShot.composition}</p>
            <p><span className="text-tertiary">镜头：</span>{selectedShot.lens ?? "默认"} · {selectedShot.fps}fps</p>
            <p><span className="text-tertiary">运镜：</span>{selectedShot.camera_movement} · {selectedShot.camera_angle}</p>
            {selectedShot.dialogue ? <p><span className="text-tertiary">对白：</span>{selectedShot.dialogue}</p> : null}
            {selectedShot.music_cue ? <p><span className="text-tertiary">音乐：</span>{selectedShot.music_cue}</p> : null}
            {selectedShot.sound_effects.length > 0 ? <p><span className="text-tertiary">音效：</span>{selectedShot.sound_effects.join("、")}</p> : null}
            {selectedShot.technique_rationale ? <p><span className="text-tertiary">技法理由：</span>{selectedShot.technique_rationale}</p> : null}
            {selectedShot.continuity_requirements.length > 0 ? (
              <p><span className="text-tertiary">连续性要求：</span>{selectedShot.continuity_requirements.join("；")}</p>
            ) : null}
          </div>
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>编辑镜头</Button>
        </>
      ) : (
        <p className="text-tertiary" style={{ fontSize: 12 }}>点击胶片带或镜头卡查看完整摄影参数。</p>
      )}
    </div>,
    [selectedShot],
  );

  if (shotsQuery.isLoading) {
    return <p className="text-tertiary" aria-live="polite">正在载入分镜…</p>;
  }

  if (shotsQuery.isError || !data) {
    return (
      <ErrorNotice
        title="尚未生成分镜"
        impact="请先确认导演方案或创作简报。"
        error={shotsQuery.error}
      />
    );
  }

  const confirm = () => {
    if (errorCount > 0 || confirmShots.isPending) return;
    withWait(
      {
        step: "编译镜头包",
        detail: "AI 正在锁定每个镜头的提示词并注入工作流参数",
        expect: "通常需要 10~40 秒",
      },
      () => confirmShots.mutateAsync(),
    )
      .then(() => toast("镜头表已确认，Prompt 包与工作流已编译", "success"))
      .catch((err) => toast("确认失败：" + (err?.message ?? "未知错误"), "error"));
  };

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <header style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h2 className="display" style={{ fontSize: 22 }}>分镜工作台</h2>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
            {shots.length} 个镜头 · 总时长 <span className="mono">{data.total_duration.toFixed(1)}s</span>
          </p>
        </div>
        <span style={{ flex: 1 }} />
        <Button
          variant="primary"
          onClick={confirm}
          disabled={errorCount > 0 || confirmShots.isPending}
          title={errorCount > 0 ? "存在错误，无法确认" : undefined}
        >
          {confirmShots.isPending ? "正在编译…" : errorCount > 0 ? `修复 ${errorCount} 个错误后确认` : "确认镜头表"}
        </Button>
      </header>

      <FilmStrip shots={shots} selectedId={selectedId} issueShotIds={issueShotIds} onSelect={(id) => setSelectedId(id === selectedId ? null : id)} />

      {issues.length > 0 ? (
        <section className="card" style={{ padding: 14, display: "grid", gap: 8 }} aria-label="校验问题">
          <h3 style={{ fontSize: 13 }}>校验问题（{issues.length}）</h3>
          {issues.map((issue) => (
            <button
              key={issue.key}
              type="button"
              onClick={() => issue.shotIds[0] && setSelectedId(issue.shotIds[0])}
              style={{
                display: "flex",
                gap: 10,
                alignItems: "baseline",
                textAlign: "left",
                padding: "8px 10px",
                borderRadius: 8,
                background: "rgb(0 0 0 / 20%)",
              }}
              className="hover-lift"
            >
              <StatusBadge
                tone={issue.severity === "error" ? "danger" : "warning"}
                label={issue.severity === "error" ? "错误" : "警告"}
              />
              <span className="tag" style={{ fontSize: 11 }}>{issue.source}</span>
              <span className="mono text-tertiary" style={{ fontSize: 11 }}>{issue.shotIds.join(", ")}</span>
              <span style={{ fontSize: 12, flex: 1 }}>
                {issue.message}
                <span className="text-tertiary"> — 建议：{issue.fix}</span>
              </span>
            </button>
          ))}
        </section>
      ) : null}

      {confirmShots.isError ? (
        <ErrorNotice title="确认镜头表失败" error={confirmShots.error} />
      ) : null}

      <div style={{ display: "grid", gap: 10 }}>
        {shots.map((shot) => (
          <ShotCard
            key={shot.shot_id}
            shot={shot}
            selected={shot.shot_id === selectedId}
            issue={issueShotIds.get(shot.shot_id)}
            onSelect={() => setSelectedId(shot.shot_id === selectedId ? null : shot.shot_id)}
          />
        ))}
      </div>

      <AnimatePresence>
        {editing && selectedShot ? (
          <ShotEditDrawer
            key={selectedShot.shot_id}
            projectId={projectId}
            shot={selectedShot}
            onClose={() => setEditing(false)}
          />
        ) : null}
      </AnimatePresence>

      <StageFooter
        done={confirmed && errorCount === 0}
        hasNext
        nextLabel="生成工作台"
        onNext={onNextStage}
      />
    </div>
  );
}
