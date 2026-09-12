import { useCallback, useEffect, useRef, useState } from "react";
import { useShell } from "../app/ShellContext";
import type { AiWaitState } from "./AiWaitOverlay";

export interface AiWaitError {
  message: string;
  /** 点击「重新生成」时重跑的操作 */
  retry: () => void;
}

interface WithWaitOptions extends AiWaitState {
  /** 请求失败时自动进入失败态（默认开启）；关闭后维持旧行为只抛错 */
  retryable?: boolean;
}

/**
 * AI 等待弹层便捷钩子：
 *   const { withWait } = useAiWait();
 *   withWait({ step: "生成剧本" }, async () => { ... });
 *
 * 请求完成自动收起；失败时弹层切换为失败态，展示错误并给出
 * 「重新生成」按钮，点击即原地重跑同一操作（弹层回到等待态）。
 * 组件卸载时自动收起。
 */
export function useAiWait() {
  const { setAiWait } = useShell();
  const [error, setError] = useState<AiWaitError | null>(null);
  const errorRef = useRef<AiWaitError | null>(null);

  useEffect(() => () => {
    setAiWait(null);
    errorRef.current = null;
  }, [setAiWait]);

  const clearError = useCallback(() => {
    setError(null);
    errorRef.current = null;
  }, []);

  const showError = useCallback(
    (message: string, retry: () => void) => {
      const next = { message, retry };
      errorRef.current = next;
      setError(next);
    },
    [],
  );

  const withWait = useCallback(
    async <T,>(options: WithWaitOptions, fn: () => Promise<T>): Promise<T> => {
      const { retryable = true, ...state } = options;
      const attempt = async (): Promise<T> => {
        setAiWait(state);
        clearError();
        try {
          return await fn();
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (retryable) {
            showError(message || "请求失败", () => {
              void attempt().catch(() => {
                /* 失败态已由内层 showError 呈现 */
              });
            });
          }
          throw err;
        }
      };
      try {
        return await attempt();
      } catch (err) {
        if (!retryable) throw err;
        // 吞掉异常：失败已通过弹层呈现，调用方的 .catch 仍可执行（toast 等）
        throw err;
      }
    },
    [setAiWait, clearError, showError],
  );

  return { withWait, error, clearError };
}
