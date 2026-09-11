import { useProject, useScreenplay } from "../../api/queries";
import type { ProjectBible } from "../../api/types";
import { ErrorNotice } from "../../components/ErrorNotice";
import { useInspector } from "../../app/App";

type LockTone = "user" | "agent" | "blocked";

function LockIcon({ tone, reason }: { tone: LockTone; reason: string }) {
  const color =
    tone === "user" ? "var(--accent)" : tone === "blocked" ? "var(--danger)" : "var(--text-tertiary)";
  return (
    <span title={reason} aria-label={reason} style={{ color: color, fontSize: 12, cursor: "help" }}>
      {tone === "blocked" ? "⛔" : "🔒"}
    </span>
  );
}

function LockedField({ label, value, tone, reason }: { label: string; value: React.ReactNode; tone: LockTone; reason: string }) {
  return (
    <div style={{ display: "grid", gap: 3 }}>
      <span className="text-tertiary" style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 5 }}>
        <LockIcon tone={tone} reason={reason} />
        {label}
      </span>
      <span style={{ fontSize: 13, lineHeight: 1.6 }}>{value}</span>
    </div>
  );
}

function bibleLocks(bible: ProjectBible) {
  const userLocked = new Set<string>();
  const blocked = new Set<string>();
  for (const c of bible.characters) {
    c.forbidden_changes.forEach((f) => blocked.add(`${c.name}·${f}`));
  }
  for (const l of bible.locations) {
    l.forbidden_changes.forEach((f) => blocked.add(`${l.name}·${f}`));
  }
  return { userLocked, blocked };
}

export function BibleStage({ projectId }: { projectId: string }) {
  const projectQuery = useProject(projectId);
  const enabled = projectQuery.data !== undefined;
  const screenplayQuery = useScreenplay(projectId, enabled);

  const pkg = screenplayQuery.data ?? null;
  const bible = pkg?.project_bible ?? null;
  const locks = bible ? bibleLocks(bible) : null;

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>圣经锁定说明</h3>
      <div style={{ display: "grid", gap: 8, fontSize: 12 }} className="text-secondary">
        <p><LockIcon tone="user" reason="" /> 金色：用户明确锁定，Agent 不可更改。</p>
        <p><LockIcon tone="agent" reason="" /> 灰色：Agent 默认值，后续版本开放修改。</p>
        <p><LockIcon tone="blocked" reason="" /> 红色：当前工作流暂不支持改动。</p>
      </div>
      {bible ? (
        <p className="text-tertiary" style={{ fontSize: 12 }}>
          {bible.characters.length} 个角色 · {bible.locations.length} 个场景 · 目标时长 {bible.target_duration}s
        </p>
      ) : null}
      <p className="text-tertiary" style={{ fontSize: 12 }}>
        第一版圣经为只读。字段级修改与影响分析将在后端提供精确更新接口后开放。
      </p>
    </div>,
    [bible],
  );

  if (screenplayQuery.isLoading) {
    return <p className="text-tertiary" aria-live="polite">正在载入剧本圣经…</p>;
  }

  if (screenplayQuery.isError || !bible || !pkg || !locks) {
    return (
      <ErrorNotice
        title="尚未生成剧本圣经"
        impact="请先确认导演方案，Agent 会在此之后生成角色与场景设定。"
        error={screenplayQuery.error}
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <header>
        <h2 className="display" style={{ fontSize: 22 }}>{bible.title}</h2>
        <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>{bible.logline}</p>
        <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          {bible.genre.map((g) => (
            <span key={g} className="tag">{g}</span>
          ))}
          <span className="tag">{bible.aspect_ratio}</span>
          <span className="tag mono">{bible.target_duration}s</span>
        </div>
      </header>

      <div style={{ display: "grid", gap: 20, gridTemplateColumns: "minmax(0, 5fr) minmax(0, 4fr)" }} className="bible-grid">
        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          <section className="card" style={{ padding: 18, display: "grid", gap: 14 }} aria-label="角色设定">
            <h3 style={{ fontSize: 15 }}>角色</h3>
            {bible.characters.map((c) => (
              <div key={c.character_id} style={{ display: "grid", gap: 10, paddingBottom: 12, borderBottom: "1px solid var(--line)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <strong style={{ fontSize: 14 }}>{c.name}</strong>
                  <span className="tag" style={{ fontSize: 11 }}>{c.narrative_role}</span>
                  {c.age_range ? <span className="tag" style={{ fontSize: 11 }}>{c.age_range}</span> : null}
                </div>
                <LockedField label="固定外观" value={c.fixed_appearance} tone="agent" reason="Agent 默认，可修改" />
                <LockedField label="固定服装" value={c.fixed_costume} tone="agent" reason="Agent 默认，可修改" />
                {c.personality.length > 0 ? (
                  <LockedField label="性格" value={c.personality.join("、")} tone="agent" reason="Agent 默认，可修改" />
                ) : null}
                {c.forbidden_changes.map((f) => (
                  <LockedField key={f} label="不可更改" value={f} tone="blocked" reason="工作流暂不支持" />
                ))}
              </div>
            ))}
          </section>

          <section className="card" style={{ padding: 18, display: "grid", gap: 14 }} aria-label="场景设定">
            <h3 style={{ fontSize: 15 }}>场景</h3>
            {bible.locations.map((l) => (
              <div key={l.location_id} style={{ display: "grid", gap: 10, paddingBottom: 12, borderBottom: "1px solid var(--line)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <strong style={{ fontSize: 14 }}>{l.name}</strong>
                  <span className="tag" style={{ fontSize: 11 }}>{l.time_of_day}</span>
                  {l.weather ? <span className="tag" style={{ fontSize: 11 }}>{l.weather}</span> : null}
                </div>
                <LockedField label="固定视觉描述" value={l.fixed_visual_description} tone="agent" reason="Agent 默认，可修改" />
                <LockedField label="光线基准" value={l.lighting_baseline} tone="agent" reason="Agent 默认，可修改" />
                {l.forbidden_changes.map((f) => (
                  <LockedField key={f} label="不可更改" value={f} tone="blocked" reason="工作流暂不支持" />
                ))}
              </div>
            ))}
          </section>

          <section className="card" style={{ padding: 18, display: "grid", gap: 12 }} aria-label="全局设定">
            <h3 style={{ fontSize: 15 }}>色彩与声音</h3>
            {bible.color_palette.length > 0 ? (
              <LockedField
                label="色彩锁"
                value={
                  <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {bible.color_palette.map((c) => (
                      <span key={c} className="tag" style={{ fontSize: 11 }}>{c}</span>
                    ))}
                  </span>
                }
                tone="agent"
                reason="Agent 默认，可修改"
              />
            ) : null}
            {bible.soundtrack_style ? (
              <LockedField label="配乐风格" value={bible.soundtrack_style} tone="agent" reason="Agent 默认，可修改" />
            ) : null}
            {bible.global_negative_prompt ? (
              <LockedField
                label="全局负向约束"
                value={<span className="mono" style={{ fontSize: 12 }}>{bible.global_negative_prompt}</span>}
                tone="agent"
                reason="Agent 默认，可修改"
              />
            ) : null}
          </section>
        </div>

        <aside className="card" style={{ padding: 18, display: "grid", gap: 12, alignContent: "start" }} aria-label="场景列表">
          <h3 style={{ fontSize: 15 }}>场景列表</h3>
          {pkg.scenes.map((s) => (
            <div key={s.scene_id} style={{ display: "grid", gap: 6, paddingBottom: 12, borderBottom: "1px solid var(--line)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="mono text-tertiary" style={{ fontSize: 11 }}>{String(s.order).padStart(2, "0")}</span>
                <strong style={{ fontSize: 13 }}>{s.heading}</strong>
                <span style={{ flex: 1 }} />
                <span className="tag mono" style={{ fontSize: 11 }}>{s.estimated_duration}s</span>
              </div>
              <p className="text-secondary" style={{ fontSize: 12 }}>{s.setup}</p>
              <p className="text-tertiary" style={{ fontSize: 12 }}>{s.purpose}</p>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
}
