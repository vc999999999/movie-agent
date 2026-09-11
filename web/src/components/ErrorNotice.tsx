import { useState, type ReactNode } from "react";
import { ApiError } from "../api/client";

interface ErrorNoticeProps {
  title: string;
  impact?: string;
  actions?: ReactNode;
  error?: unknown;
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return `HTTP ${error.status}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

export function ErrorNotice({ title, impact, actions, error }: ErrorNoticeProps) {
  const [showDetail, setShowDetail] = useState(false);
  return (
    <div
      role="alert"
      className="card"
      style={{
        padding: "14px 16px",
        borderColor: "rgb(255 69 58 / 40%)",
        display: "grid",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span aria-hidden="true" style={{ color: "var(--danger)" }}>⚠</span>
        <strong>{title}</strong>
      </div>
      {impact ? <p className="text-secondary" style={{ fontSize: 13 }}>{impact}</p> : null}
      {actions ? <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div> : null}
      {error !== undefined ? (
        <div>
          <button
            type="button"
            className="text-tertiary"
            style={{ fontSize: 12, textDecoration: "underline" }}
            onClick={() => setShowDetail((v) => !v)}
            aria-expanded={showDetail}
          >
            {showDetail ? "收起技术详情" : "技术详情"}
          </button>
          {showDetail ? (
            <pre
              className="mono"
              style={{
                marginTop: 8,
                fontSize: 11,
                color: "var(--text-tertiary)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "rgb(0 0 0 / 30%)",
                borderRadius: 8,
                padding: 10,
              }}
            >
              {describe(error)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
