import type { CSSProperties } from "react";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

interface StatusBadgeProps {
  tone?: Tone;
  label: string;
  icon?: string;
}

const tones: Record<Tone, { color: string; border: string; bg: string }> = {
  neutral: { color: "var(--text-secondary)", border: "var(--line)", bg: "transparent" },
  accent: { color: "var(--accent-soft)", border: "rgb(200 169 107 / 45%)", bg: "var(--accent-tint)" },
  success: { color: "var(--success)", border: "rgb(48 209 88 / 35%)", bg: "rgb(48 209 88 / 10%)" },
  warning: { color: "var(--warning)", border: "rgb(255 214 10 / 35%)", bg: "rgb(255 214 10 / 8%)" },
  danger: { color: "var(--danger)", border: "rgb(255 69 58 / 40%)", bg: "rgb(255 69 58 / 10%)" },
  info: { color: "var(--info)", border: "rgb(100 210 255 / 35%)", bg: "rgb(100 210 255 / 8%)" },
};

const style: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  borderRadius: "var(--radius-pill)",
  border: "1px solid",
  padding: "2px 10px",
  fontSize: 12,
  fontWeight: 500,
  whiteSpace: "nowrap",
};

export function StatusBadge({ tone = "neutral", label, icon }: StatusBadgeProps) {
  const t = tones[tone];
  return (
    <span style={{ ...style, color: t.color, borderColor: t.border, background: t.bg }}>
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      {label}
    </span>
  );
}
