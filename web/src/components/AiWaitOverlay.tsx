import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "./Button";

export interface AiWaitState {
  /** 正在进行的 AI 步骤名，如"生成导演方案" */
  step: string;
  /** 这一步具体在做什么（可选的补充说明） */
  detail?: string;
  /** 预期等待提示，如"通常需要 20~60 秒" */
  expect?: string;
}

export interface AiWaitError {
  message: string;
  /** 点击「重新生成」时重跑的操作 */
  retry: () => void;
}

export type AiWaitDisplay = AiWaitState & { error?: AiWaitError | null };

const DEFAULT_EXPECT = "魔搭创空间免费资源生成较慢，请耐心等待";

/**
 * 全局 AI 等待弹层：任何 AI 请求进行中时显示。
 * - 每次步骤切换重新计时
 * - 超过 15 秒后追加"仍在处理"安抚文案，避免用户以为卡死
 * - 失败时切换为失败态：显示错误原因 + 「重新生成」按钮，点击原地重试
 * - 遮罩不可点击穿透，防止等待中重复提交
 */
export function AiWaitOverlay({ state }: { state: AiWaitDisplay | null }) {
  const [elapsed, setElapsed] = useState(0);

  const failed = Boolean(state?.error);
  const stepKey = failed ? `err-${state?.error?.message}` : state?.step ?? "";

  useEffect(() => {
    setElapsed(0);
    if (failed) return; // 失败态不需要计时
    const timer = setInterval(() => setElapsed((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [stepKey, failed]);

  const retry = () => state?.error?.retry();

  return (
    <AnimatePresence>
      {state ? (
        <motion.div
          key="ai-wait-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          role="alert"
          aria-live="polite"
          aria-busy={!failed}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 120,
            background: "rgb(0 0 0 / 60%)",
            backdropFilter: "blur(4px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
        >
          <motion.div
            key={`ai-wait-${stepKey}`}
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
            className="glass-strong"
            style={{
              width: "100%",
              maxWidth: 400,
              borderRadius: "var(--radius-panel, 16px)",
              padding: "26px 28px",
              display: "grid",
              gap: 12,
              textAlign: "center",
              justifyItems: "center",
            }}
          >
            {failed ? (
              <>
                <div
                  aria-hidden="true"
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: "50%",
                    display: "grid",
                    placeItems: "center",
                    fontSize: 18,
                    background: "rgb(255 69 58 / 12%)",
                    color: "var(--danger)",
                  }}
                >
                  ✕
                </div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>
                    {state.step}失败
                  </div>
                  <div className="text-danger" style={{ fontSize: 12, marginTop: 4, maxWidth: 300, wordBreak: "break-word" }}>
                    {state.error?.message}
                  </div>
                </div>
                <div className="text-tertiary" style={{ fontSize: 11 }}>
                  常见于免费资源排队繁忙，稍等片刻重新生成即可
                </div>
                <Button variant="primary" onClick={retry} style={{ minWidth: 160 }}>
                  重新生成
                </Button>
              </>
            ) : (
              <>
                <Spinner />
                <div>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>AI 正在{state.step}</div>
                  {state.detail ? (
                    <div className="text-secondary" style={{ fontSize: 12, marginTop: 4 }}>
                      {state.detail}
                    </div>
                  ) : null}
                </div>
                <div className="mono text-tertiary" style={{ fontSize: 12 }} aria-live="off">
                  已等待 {elapsed} 秒{state.expect ? ` · ${state.expect}` : ""}
                </div>
                {elapsed >= 15 ? (
                  <div className="text-tertiary" style={{ fontSize: 11, maxWidth: 300 }}>
                    仍在处理中，免费资源偶有排队，请勿关闭或刷新页面
                  </div>
                ) : null}
                <div className="text-tertiary" style={{ fontSize: 11 }}>
                  {DEFAULT_EXPECT}
                </div>
              </>
            )}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function Spinner() {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 34,
        height: 34,
        borderRadius: "50%",
        border: "3px solid rgb(200 169 107 / 25%)",
        borderTopColor: "var(--accent)",
        animation: "ai-wait-spin 0.9s linear infinite",
      }}
    />
  );
}
