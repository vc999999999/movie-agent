import { useCallback, useEffect } from "react";
import { useShell } from "../app/ShellContext";
import type { AiWaitState } from "./AiWaitOverlay";

export function useAiWait() {
  const { setAiWait } = useShell();
  useEffect(() => () => setAiWait(null), [setAiWait]);
  const withWait = useCallback(async <T,>(state: AiWaitState, fn: () => Promise<T>): Promise<T> => {
    setAiWait(state);
    try { return await fn(); }
    finally { setAiWait(null); }
  }, [setAiWait]);
  return { withWait };
}
