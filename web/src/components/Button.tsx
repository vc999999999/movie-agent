import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  children: ReactNode;
}

const base: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 6,
  borderRadius: "var(--radius-control)",
  fontWeight: 500,
  whiteSpace: "nowrap",
  border: "1px solid transparent",
};

const variants: Record<Variant, CSSProperties> = {
  primary: {
    background: "var(--accent)",
    color: "#1c1c1e",
    borderColor: "transparent",
  },
  secondary: {
    background: "var(--canvas-overlay)",
    color: "var(--text)",
    borderColor: "var(--line)",
  },
  ghost: {
    background: "transparent",
    color: "var(--text-secondary)",
    borderColor: "var(--line)",
  },
  danger: {
    background: "transparent",
    color: "var(--danger)",
    borderColor: "rgb(255 69 58 / 40%)",
  },
};

const sizes = {
  sm: { padding: "5px 12px", fontSize: 12 },
  md: { padding: "9px 18px", fontSize: 14 },
};

export function Button({ variant = "secondary", size = "md", children, style, className = "", ...rest }: ButtonProps) {
  return (
    <button
      className={`press ${className}`}
      style={{ ...base, ...variants[variant], ...sizes[size], ...style }}
      {...rest}
    >
      {children}
    </button>
  );
}
