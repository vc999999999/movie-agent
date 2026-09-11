import { useCallback, useEffect, useState } from "react";
import { isStageId, type StageId } from "./stages";

export interface UrlState {
  projectId: string | null;
  stage: StageId | null;
}

function readUrl(): UrlState {
  const params = new URLSearchParams(window.location.search);
  const stageParam = params.get("stage");
  return {
    projectId: params.get("project"),
    stage: isStageId(stageParam) ? stageParam : null,
  };
}

export function useUrlState(): [UrlState, (next: Partial<UrlState>) => void] {
  const [state, setState] = useState<UrlState>(readUrl);

  useEffect(() => {
    const onPop = () => setState(readUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((next: Partial<UrlState>) => {
    setState((prev) => {
      const merged: UrlState = {
        projectId: next.projectId !== undefined ? next.projectId : prev.projectId,
        stage: next.stage !== undefined ? next.stage : prev.stage,
      };
      const params = new URLSearchParams();
      if (merged.projectId) params.set("project", merged.projectId);
      if (merged.stage) params.set("stage", merged.stage);
      const url = merged.projectId ? `/studio?${params.toString()}` : "/";
      window.history.pushState(null, "", url);
      return merged;
    });
  }, []);

  return [state, update];
}
