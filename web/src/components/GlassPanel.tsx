import type { CSSProperties, ReactNode } from "react";

interface GlassPanelProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  strong?: boolean;
  role?: string;
  ariaLabel?: string;
}

export function GlassPanel({ children, className = "", style, strong = false, role, ariaLabel }: GlassPanelProps) {
  return (
    <div
      className={`${strong ? "glass-strong" : "glass"} ${className}`}
      style={{ borderRadius: "var(--radius-panel)", ...style }}
      role={role}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}
