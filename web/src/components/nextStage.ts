import { useCallback } from "react";
import { STAGES, type StageId } from "../app/stages";

/**
 * 返回跳转到指定阶段"下一个阶段"的回调。
 * 通过自定义事件与 App 的 URL 状态通信（避免各阶段直接耦合路由实现）。
 */
export function useNextStage(current: StageId): () => void {
  return useCallback(() => {
    const def = STAGES.find((s) => s.id === current);
    const next = def ? STAGES[def.index + 1] : undefined;
    if (!next) return;
    window.dispatchEvent(new CustomEvent("movie-agent:navigate-stage", { detail: next.id }));
  }, [current]);
}

/** 订阅阶段跳转事件（App 层挂一次）。 */
export function onNextStageEvent(handler: (stage: StageId) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<StageId>).detail);
  window.addEventListener("movie-agent:navigate-stage", listener);
  return () => window.removeEventListener("movie-agent:navigate-stage", listener);
}
