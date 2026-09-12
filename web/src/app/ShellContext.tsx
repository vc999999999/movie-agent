import { createContext, useCallback, useContext, useMemo, useReducer, useState, type ReactNode } from "react";
import type { AiWaitState } from "../components/AiWaitOverlay";

export type DockTaskStatus = "submitted" | "running" | "success" | "failed";

export interface DockTask {
  id: string;
  label: string;
  status: DockTaskStatus;
  detail?: string;
  createdAt: number;
}

type DockAction =
  | { type: "add"; task: DockTask }
  | { type: "update"; id: string; status: DockTaskStatus; detail?: string }
  | { type: "clear_finished" };

function dockReducer(state: DockTask[], action: DockAction): DockTask[] {
  switch (action.type) {
    case "add":
      return [action.task, ...state].slice(0, 50);
    case "update":
      return state.map((t) =>
        t.id === action.id
          ? { ...t, status: action.status, detail: action.detail ?? t.detail }
          : t,
      );
    case "clear_finished":
      return state.filter((t) => t.status === "submitted" || t.status === "running");
  }
}

interface ShellContextValue {
  aiWait: AiWaitState | null;
  setAiWait: (state: AiWaitState | null) => void;
  inspector: ReactNode;
  setInspector: (node: ReactNode) => void;
  inspectorOpen: boolean;
  setInspectorOpen: (open: boolean) => void;
  dockTasks: DockTask[];
  addDockTask: (task: Omit<DockTask, "createdAt">) => void;
  updateDockTask: (id: string, status: DockTaskStatus, detail?: string) => void;
  clearFinishedDockTasks: () => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) throw new Error("useShell must be used inside ShellProvider");
  return ctx;
}

export function ShellProvider({ children }: { children: ReactNode }) {
  const [inspector, setInspectorNode] = useState<ReactNode>(null);
  const [aiWait, setAiWait] = useState<AiWaitState | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [dockTasks, dispatch] = useReducer(dockReducer, []);

  const setInspector = useCallback((node: ReactNode) => setInspectorNode(node), []);
  const addDockTask = useCallback(
    (task: Omit<DockTask, "createdAt">) => dispatch({ type: "add", task: { ...task, createdAt: Date.now() } }),
    [],
  );
  const updateDockTask = useCallback(
    (id: string, status: DockTaskStatus, detail?: string) => dispatch({ type: "update", id, status, detail }),
    [],
  );
  const clearFinishedDockTasks = useCallback(() => dispatch({ type: "clear_finished" }), []);

  const value = useMemo(
    () => ({
      aiWait,
      setAiWait,
      inspector,
      setInspector,
      inspectorOpen,
      setInspectorOpen,
      dockTasks,
      addDockTask,
      updateDockTask,
      clearFinishedDockTasks,
    }),
    [aiWait, inspector, setInspector, inspectorOpen, dockTasks, addDockTask, updateDockTask, clearFinishedDockTasks],
  );

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
