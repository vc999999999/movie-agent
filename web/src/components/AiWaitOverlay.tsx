import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

export interface AiWaitState { step: string; detail?: string; expect?: string; }
export type AiWaitDisplay = AiWaitState;

export function AiWaitOverlay({ state }: { state: AiWaitDisplay | null }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!state) return;
    const timer = window.setInterval(() => setElapsed(value => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [state?.step]);
  return <AnimatePresence>{state ? <motion.div
    key="ai-wait" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
    transition={{ duration: .16 }} role="status" aria-live="polite" aria-busy="true"
    className="ai-wait-backdrop">
    <div className="glass-strong ai-wait-panel"><h2>{state.step}</h2>{state.detail ? <p>{state.detail}</p> : null}<p className="mono text-tertiary">已等待 {elapsed} 秒{state.expect ? ` · ${state.expect}` : ""}</p>{elapsed >= 15 ? <p>仍在等待服务响应，请稍候。</p> : null}</div>
  </motion.div> : null}</AnimatePresence>;
}
