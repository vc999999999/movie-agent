import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

export interface AiWaitState {
  /** 正在进行的 AI 步骤名，如"生成导演方案" */
  step: string;
  /** 这一步具体在做什么（可选的补充说明） */
  detail?: string;
  /** 预期等待提示，如"通常需要 20~60 秒" */
  expect?: string;
}

const DEFAULT_EXPECT = "魔搭创空间免费资源生成较慢，请耐心等待";

/**
 * 全局 AI 等待弹层：任何 AI 请求进行中时显示。
 * - 每次步骤切换重新计时
 * - 超过 15 秒后追加"仍在处理"安抚文案，避免用户以为卡死
 * - 遮罩不可点击穿透，防止等待中重复提交
 */
export function AiWaitOverlay({ state }: { state: AiWaitState | null }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!state) {
      setElapsed(0);
      return;
    }
    setElapsed(0);
    const timer = setInterval(() => setElapsed((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [state?.step, state]);

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
          aria-busy="true"
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
            key={`ai-wait-${state.step}`}
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
