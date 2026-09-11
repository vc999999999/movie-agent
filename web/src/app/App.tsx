import { useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useProject } from "../api/queries";
import { ErrorNotice } from "../components/ErrorNotice";
import { useShell } from "./ShellContext";
import { STAGES, maxStageIndex, type StageId } from "./stages";
import { StudioShell } from "./StudioShell";
import { useUrlState } from "./urlState";
import { BriefStage, BriefHome } from "../features/brief";
import { AuteurStage } from "../features/auteur";
import { TreatmentsStage } from "../features/treatments";
import { BibleStage } from "../features/bible";
import { StoryboardStage } from "../features/storyboard";
import { GenerationStage } from "../features/generation";
import { PreviewStage } from "../features/preview";

export function useInspector(node: ReactNode, deps: readonly unknown[]) {
  const { setInspector } = useShell();
  useEffect(() => {
    setInspector(node);
    return () => setInspector(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function StageView({ stage, projectId }: { stage: StageId; projectId: string }) {
  switch (stage) {
    case "brief":
      return <BriefStage projectId={projectId} />;
    case "auteur":
      return <AuteurStage projectId={projectId} />;
    case "treatments":
      return <TreatmentsStage projectId={projectId} />;
    case "bible":
      return <BibleStage projectId={projectId} />;
    case "storyboard":
      return <StoryboardStage projectId={projectId} />;
    case "generation":
      return <GenerationStage projectId={projectId} />;
    case "preview":
      return <PreviewStage projectId={projectId} />;
  }
}

export default function App() {
  const [{ projectId, stage }, setUrl] = useUrlState();
  const projectQuery = useProject(projectId);

  const project = projectQuery.data?.project ?? null;
  const maxIdx = project ? maxStageIndex(project.status) : 0;
  const fallbackStage = STAGES[maxIdx].id;
  const requestedIdx = stage ? STAGES.find((s) => s.id === stage)?.index ?? 0 : -1;
  const activeStage: StageId =
    stage !== null && requestedIdx >= 0 && requestedIdx <= maxIdx ? stage : fallbackStage;

  if (!projectId) {
    return <BriefHome onCreated={(id) => setUrl({ projectId: id, stage: "brief" })} onOpen={(id) => setUrl({ projectId: id })} />;
  }

  if (projectQuery.isError) {
    return (
      <div style={{ maxWidth: 560, margin: "120px auto", padding: 24 }}>
        <ErrorNotice
          title="无法打开项目"
          impact="项目可能已被删除，或服务暂时不可用。"
          error={projectQuery.error}
          actions={
            <button type="button" className="tag tag-accent hover-lift" onClick={() => setUrl({ projectId: null, stage: null })}>
              返回创意首页
            </button>
          }
        />
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ display: "grid", placeItems: "center", height: "100%" }} aria-live="polite">
        <span className="text-tertiary">正在载入项目…</span>
      </div>
    );
  }

  return (
    <StudioShell
      project={project}
      stage={activeStage}
      maxStageIndex={maxIdx}
      onSelectStage={(s) => setUrl({ stage: s })}
      onNewProject={() => setUrl({ projectId: null, stage: null })}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={activeStage}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          style={{ display: "grid", gap: 20 }}
        >
          <StageView stage={activeStage} projectId={project.id} />
        </motion.div>
      </AnimatePresence>
    </StudioShell>
  );
}
