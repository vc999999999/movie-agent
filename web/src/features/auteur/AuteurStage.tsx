import { useEffect, useMemo, useState } from "react";
import {
  useApplyAuteurProfile,
  useAuteurContext,
  useAuteurProfiles,
  useClearAuteurProfile,
} from "../../api/queries";
import type { AuteurIntensity, AuteurProfile } from "../../api/types";
import { Button } from "../../components/Button";
import { ErrorNotice } from "../../components/ErrorNotice";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toast";
import { useInspector } from "../../app/App";

const INTENSITY_LABEL: Record<AuteurIntensity, string> = {
  subtle: "轻度",
  balanced: "平衡",
  strong: "强烈",
};

const DOMAIN_LABEL: Record<string, string> = {
  narrative: "叙事",
  camera: "摄影",
  editing: "剪辑",
  sound: "声音",
};

export function AuteurStage({ projectId }: { projectId: string }) {
  const profilesQuery = useAuteurProfiles();
  const contextQuery = useAuteurContext(projectId, true);
  const applyProfile = useApplyAuteurProfile(projectId);
  const clearProfile = useClearAuteurProfile(projectId);
  const { toast } = useToast();

  const existing = contextQuery.data ?? null;
  const [profileId, setProfileId] = useState<string | null>(null);
  const [variantId, setVariantId] = useState<string | null>(null);
  const [intensity, setIntensity] = useState<AuteurIntensity>("balanced");
  const [preserve, setPreserve] = useState<string[]>([]);
  const [preserveInput, setPreserveInput] = useState("");

  useEffect(() => {
    if (existing) {
      setProfileId(existing.profile.profile_id);
      setVariantId(existing.selection.variant_id);
      setIntensity(existing.selection.intensity);
      setPreserve(existing.selection.preserve);
    }
  }, [existing]);

  const profiles = profilesQuery.data ?? [];
  const profile: AuteurProfile | null = useMemo(
    () => profiles.find((p) => p.profile_id === profileId) ?? null,
    [profiles, profileId],
  );
  const variant = useMemo(() => {
    if (!profile) return null;
    return profile.variants.find((v) => v.variant_id === variantId) ?? profile.variants.find((v) => v.variant_id === profile.default_variant_id) ?? null;
  }, [profile, variantId]);

  const previewTechnique = variant?.techniques[0] ?? null;

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>技法预演</h3>
      {variant && previewTechnique ? (
        <>
          <p className="text-secondary" style={{ fontSize: 12 }}>
            当前模式：<strong style={{ color: "var(--text)" }}>{variant.name}</strong> · 强度 {INTENSITY_LABEL[intensity]}
          </p>
          {variant.techniques.map((t) => (
            <div key={t.technique_id} className="card" style={{ padding: 12, display: "grid", gap: 6 }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <strong style={{ fontSize: 13 }}>{t.name}</strong>
                <span className="tag" style={{ fontSize: 11 }}>{DOMAIN_LABEL[t.domain] ?? t.domain}</span>
              </div>
              <p className="text-secondary" style={{ fontSize: 12 }}>原场景：{t.instruction}</p>
              <p className="text-secondary" style={{ fontSize: 12 }}>观众效果：{t.viewer_effect}</p>
              <p className="text-tertiary" style={{ fontSize: 12 }}>生成方式：{t.generation_note}</p>
            </div>
          ))}
          {preserve.length > 0 ? (
            <p className="text-tertiary" style={{ fontSize: 12 }}>
              必须保留：{preserve.join("、")}
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-tertiary" style={{ fontSize: 12 }}>选择一个名导档案与代表作模式后，这里会预演技法如何改变场景。</p>
      )}
    </div>,
    [variant, intensity, preserve, previewTechnique],
  );

  const addPreserve = () => {
    const value = preserveInput.trim();
    if (!value || preserve.includes(value) || preserve.length >= 20) return;
    setPreserve((p) => [...p, value]);
    setPreserveInput("");
  };

  const apply = () => {
    if (!profile || applyProfile.isPending) return;
    applyProfile.mutate(
      {
        profile_id: profile.profile_id,
        variant_id: variant?.variant_id,
        intensity,
        preserve,
      },
      { onSuccess: () => toast("名导技法已应用", "success") },
    );
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <header>
        <h2 className="display" style={{ fontSize: 22 }}>导演技法工作室</h2>
        <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
          选择一套研究性归纳的导演技法模式，控制应用强度与必须保留的内容。
        </p>
      </header>

      {profilesQuery.isError ? (
        <ErrorNotice title="无法载入名导档案" error={profilesQuery.error} />
      ) : null}

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {profiles.map((p) => {
          const isSelected = profileId === p.profile_id;
          return (
            <button
              key={p.profile_id}
              type="button"
              className="card hover-lift"
              style={{
                padding: 18,
                textAlign: "left",
                display: "grid",
                gap: 8,
                borderColor: isSelected ? "rgb(200 169 107 / 50%)" : undefined,
              }}
              onClick={() => {
                setProfileId(p.profile_id);
                setVariantId(p.default_variant_id);
              }}
              aria-pressed={isSelected}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <strong style={{ fontSize: 15 }}>{p.director_name}</strong>
                {existing?.profile.profile_id === p.profile_id ? <StatusBadge tone="accent" label="已应用" /> : null}
              </div>
              <span className="text-accent" style={{ fontSize: 12 }}>{p.label}</span>
              <p className="text-secondary" style={{ fontSize: 13 }}>{p.description}</p>
              <p className="text-tertiary" style={{ fontSize: 11 }}>{p.disclaimer}</p>
            </button>
          );
        })}
      </div>

      {profile ? (
        <section aria-label="代表作模式" style={{ display: "grid", gap: 12 }}>
          <h3 style={{ fontSize: 15 }}>代表作模式</h3>
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
            {profile.variants.map((v) => {
              const isActive = variant?.variant_id === v.variant_id;
              return (
                <button
                  key={v.variant_id}
                  type="button"
                  className="card hover-lift"
                  style={{
                    padding: 14,
                    textAlign: "left",
                    display: "grid",
                    gap: 6,
                    borderColor: isActive ? "rgb(200 169 107 / 50%)" : undefined,
                  }}
                  onClick={() => setVariantId(v.variant_id)}
                  aria-pressed={isActive}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <strong style={{ fontSize: 14 }}>{v.name}</strong>
                    {isActive ? <StatusBadge tone="accent" label="当前" /> : null}
                  </div>
                  <span className="text-tertiary" style={{ fontSize: 12 }}>
                    参考作品：{v.reference_works.join("、")}
                  </span>
                  <span className="text-secondary" style={{ fontSize: 12 }}>
                    适合：{v.best_for.join("、")}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="card" style={{ padding: 18, display: "grid", gap: 14 }}>
            <div>
              <span className="text-secondary" style={{ fontSize: 13 }}>应用强度</span>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }} role="radiogroup" aria-label="应用强度">
                {(Object.keys(INTENSITY_LABEL) as AuteurIntensity[]).map((level) => (
                  <button
                    key={level}
                    type="button"
                    role="radio"
                    aria-checked={intensity === level}
                    className={`tag hover-lift ${intensity === level ? "tag-accent" : ""}`}
                    style={{ padding: "6px 14px", fontSize: 13 }}
                    onClick={() => setIntensity(level)}
                  >
                    {INTENSITY_LABEL[level]}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className="text-secondary" style={{ fontSize: 13 }}>必须保留的内容</span>
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
                {preserve.map((item) => (
                  <span key={item} className="tag tag-accent" style={{ fontSize: 12 }}>
                    {item}
                    <button
                      type="button"
                      aria-label={`移除 ${item}`}
                      onClick={() => setPreserve((p) => p.filter((x) => x !== item))}
                      style={{ color: "inherit", fontSize: 12 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
                <input
                  value={preserveInput}
                  onChange={(e) => setPreserveInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addPreserve();
                    }
                  }}
                  placeholder="例如：女儿的红色围巾"
                  style={{ fontSize: 13, flex: 1, minWidth: 160 }}
                  aria-label="新增必须保留的内容"
                />
                <Button size="sm" variant="ghost" onClick={addPreserve} disabled={!preserveInput.trim()}>
                  添加
                </Button>
              </div>
            </div>

            {applyProfile.isError ? (
              <ErrorNotice title="应用名导技法失败" error={applyProfile.error} />
            ) : null}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              {existing ? (
                <Button
                  variant="danger"
                  onClick={() => clearProfile.mutate(undefined, { onSuccess: () => toast("已移除名导技法", "info") })}
                  disabled={clearProfile.isPending}
                >
                  移除技法
                </Button>
              ) : null}
              <Button variant="primary" onClick={apply} disabled={applyProfile.isPending}>
                {applyProfile.isPending ? "应用中…" : "应用技法"}
              </Button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
