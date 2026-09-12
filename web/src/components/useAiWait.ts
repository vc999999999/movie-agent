import { useCallback, useEffect, useRef } from "react";
import { useShell } from "../app/ShellContext";
import type { AiWaitState } from "./AiWaitOverlay";

/**
 * AI 等待弹层的便捷钩子：
 *   const { withWait } = useAiWait();
 *   withWait({ step: "生成剧本" }, async () => { ... });
 * 请求完成/失败自动收起；组件卸载时也会收起。
 */
export function useAiWait() {
  const { setAiWait } = useShell();
  const activeRef = useRef(false);

  useEffect(() => () => {
    if (activeRef.current) setAiWait(null);
  }, [setAiWait]);

  const withWait = useCallback(
    async <T,>(state: AiWaitState, fn: () => Promise<T>): Promise<T> => {
      activeRef.current = true;
      setAiWait(state);
      try {
        return await fn();
      } finally {
        activeRef.current = false;
        setAiWait(null);
      }
    },
    [setAiWait],
  );

  return { withWait, setAiWait };
}
