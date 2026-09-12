import { useCallback, useEffect } from "react";
import { useShell } from "../app/ShellContext";
import type { AiWaitState } from "./AiWaitOverlay";

interface WithWaitOptions extends AiWaitState {
  /** 请求失败时自动进入失败态（默认开启）；关闭后失败直接收起弹层并抛错 */
  retryable?: boolean;
}

/**
 * AI 等待弹层便捷钩子：
 *   const { withWait } = useAiWait();
 *   withWait({ step: "生成剧本" }, async () => { ... });
 *
 * 生命周期全部通过全局 aiWait 驱动：
 * - 开始：置为等待态
 * - 成功：收起（setAiWait(null)）
 * - 失败：保持可见并切换为失败态（error 附在 aiWait 上），「重新生成」原地重跑
 * - 组件卸载时收起，避免残留
 */
export function useAiWait() {
  const { setAiWait } = useShell();

  useEffect(() => () => setAiWait(null), [setAiWait]);

  const withWait = useCallback(
    async <T,>(options: WithWaitOptions, fn: () => Promise<T>): Promise<T> => {
      const { retryable = true, ...state } = options;
      const attempt = async (): Promise<T> => {
        setAiWait(state);
        try {
          const result = await fn();
          setAiWait(null);
          return result;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          if (retryable) {
            const retry = () => {
              void attempt().catch(() => {
                /* 失败态已由内层呈现 */
              });
            };
            setAiWait({ ...state, error: { message: message || "请求失败", retry } });
          } else {
            setAiWait(null);
          }
          throw err;
        }
      };
      return attempt();
    },
    [setAiWait],
  );

  return { withWait };
}
