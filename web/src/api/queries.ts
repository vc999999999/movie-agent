import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiJson, encodeSeg } from "./client";
import type {
  AuteurContext,
  AuteurIntensity,
  AuteurProfile,
  CreateProjectResponse,
  CreativeBrief,
  PackagesResponse,
  ProductionPack,
  Project,
  ProjectDetailResponse,
  QuestionsResponse,
  RenderRun,
  ScreenplayPackage,
  ShotsResponse,
  ShotSpec,
  TreatmentPackage,
} from "./types";

export const queryKeys = {
  project: (id: string) => ["project", id] as const,
  projectList: ["projects"] as const,
  questions: (id: string) => ["questions", id] as const,
  auteurProfiles: ["auteur-profiles"] as const,
  auteurContext: (id: string) => ["auteur-context", id] as const,
  productionPacks: ["production-packs"] as const,
  treatments: (id: string) => ["treatments", id] as const,
  screenplay: (id: string) => ["screenplay", id] as const,
  shots: (id: string) => ["shots", id] as const,
  packages: (id: string) => ["packages", id] as const,
  render: (id: string) => ["render", id] as const,
};

// --- Queries ---

export function useProjectList() {
  return useQuery({
    queryKey: queryKeys.projectList,
    queryFn: () => apiJson<Project[]>("/api/projects"),
    retry: 1,
  });
}

export function useProject(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.project(projectId ?? ""),
    queryFn: () => apiJson<ProjectDetailResponse>(`/api/projects/${encodeSeg(projectId!)}`),
    enabled: projectId !== null,
    retry: 1,
  });
}

export function useQuestions(projectId: string | null) {
  return useQuery({
    queryKey: queryKeys.questions(projectId ?? ""),
    queryFn: () => apiJson<QuestionsResponse>(`/api/projects/${encodeSeg(projectId!)}/questions`),
    enabled: projectId !== null,
    retry: 1,
  });
}

export function useAuteurProfiles() {
  return useQuery({
    queryKey: queryKeys.auteurProfiles,
    queryFn: () => apiJson<AuteurProfile[]>("/api/auteur-profiles"),
    staleTime: Infinity,
    retry: 1,
  });
}

export function useAuteurContext(projectId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.auteurContext(projectId ?? ""),
    queryFn: () => apiJson<AuteurContext>(`/api/projects/${encodeSeg(projectId!)}/auteur-profile`),
    enabled: projectId !== null && enabled,
    retry: false,
  });
}

export function useProductionPacks() {
  return useQuery({
    queryKey: queryKeys.productionPacks,
    queryFn: () => apiJson<ProductionPack[]>("/api/production-packs"),
    staleTime: Infinity,
    retry: 1,
  });
}

export function useTreatments(projectId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.treatments(projectId ?? ""),
    queryFn: () => apiJson<TreatmentPackage>(`/api/projects/${encodeSeg(projectId!)}/treatments`),
    enabled: projectId !== null && enabled,
    retry: false,
  });
}

export function useScreenplay(projectId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.screenplay(projectId ?? ""),
    queryFn: () => apiJson<ScreenplayPackage>(`/api/projects/${encodeSeg(projectId!)}/screenplay`),
    enabled: projectId !== null && enabled,
    retry: false,
  });
}

export function useShots(projectId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.shots(projectId ?? ""),
    queryFn: () => apiJson<ShotsResponse>(`/api/projects/${encodeSeg(projectId!)}/shots`),
    enabled: projectId !== null && enabled,
    retry: false,
  });
}

export function usePackages(projectId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.packages(projectId ?? ""),
    queryFn: () => apiJson<PackagesResponse>(`/api/projects/${encodeSeg(projectId!)}/packages`),
    enabled: projectId !== null && enabled,
    retry: false,
  });
}

export function useRenderRun(renderId: string | null) {
  return useQuery({
    queryKey: queryKeys.render(renderId ?? ""),
    queryFn: () => apiJson<RenderRun>(`/api/renders/${encodeSeg(renderId!)}`),
    enabled: renderId !== null,
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });
}

// --- Mutations (no automatic retry on writes) ---

function useInvalidator() {
  const qc = useQueryClient();
  return {
    invalidateProject: (id: string) => {
      void qc.invalidateQueries({ queryKey: queryKeys.project(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.projectList });
    },
    invalidateDownstream: (id: string) => {
      void qc.invalidateQueries({ queryKey: queryKeys.treatments(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.screenplay(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.shots(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.packages(id) });
    },
    invalidateFromTreatment: (id: string) => {
      void qc.invalidateQueries({ queryKey: queryKeys.screenplay(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.shots(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.packages(id) });
    },
    invalidateFromShot: (id: string) => {
      void qc.invalidateQueries({ queryKey: queryKeys.shots(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.packages(id) });
    },
  };
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { source_text: string; title?: string }) =>
      apiJson<CreateProjectResponse>("/api/projects", { method: "POST", body: input }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.project(data.project.id), {
        project: data.project,
        messages: [],
      });
      void qc.invalidateQueries({ queryKey: queryKeys.projectList });
    },
  });
}

export function useSendMessage(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (content: string) =>
      apiJson<QuestionsResponse>(`/api/projects/${encodeSeg(projectId)}/messages`, {
        method: "POST",
        body: { content },
      }),
    onSuccess: (data) => {
      inv.invalidateProject(projectId);
      void inv;
      return data;
    },
  });
}

export function useSubmitAnswers(projectId: string) {
  const inv = useInvalidator();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (answers: { field: string; answer: string }[]) =>
      apiJson<QuestionsResponse>(`/api/projects/${encodeSeg(projectId)}/answers`, {
        method: "POST",
        body: { answers },
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.questions(projectId), data);
      inv.invalidateProject(projectId);
    },
  });
}

export function useUpdateBrief(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (updates: Partial<CreativeBrief>) =>
      apiJson<CreativeBrief>(`/api/projects/${encodeSeg(projectId)}/brief`, {
        method: "PATCH",
        body: { updates },
      }),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      inv.invalidateDownstream(projectId);
    },
  });
}

export function useConfirmBrief(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (briefData?: Record<string, unknown>) =>
      apiJson<{ status: string; brief: CreativeBrief }>(
        `/api/projects/${encodeSeg(projectId)}/brief/confirm`,
        { method: "POST", body: briefData },
      ),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      inv.invalidateFromTreatment(projectId);
    },
  });
}

export function useApplyAuteurProfile(projectId: string) {
  const inv = useInvalidator();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { profile_id: string; variant_id?: string; intensity: AuteurIntensity; preserve: string[] }) =>
      apiJson<AuteurContext>(`/api/projects/${encodeSeg(projectId)}/auteur-profile`, {
        method: "PUT",
        body: input,
      }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.auteurContext(projectId), data);
      inv.invalidateProject(projectId);
      inv.invalidateDownstream(projectId);
    },
  });
}

export function useClearAuteurProfile(projectId: string) {
  const inv = useInvalidator();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<{ status: string }>(`/api/projects/${encodeSeg(projectId)}/auteur-profile`, { method: "DELETE" }),
    onSuccess: () => {
      qc.removeQueries({ queryKey: queryKeys.auteurContext(projectId) });
      inv.invalidateProject(projectId);
      inv.invalidateDownstream(projectId);
    },
  });
}

export function useGenerateTreatments(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<TreatmentPackage>(`/api/projects/${encodeSeg(projectId)}/treatments/generate`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.treatments(projectId), data);
    },
  });
}

export function useConfirmTreatment(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (input: { treatment_id: string; production_pack_id?: string }) =>
      apiJson<{ status: string }>(
        `/api/projects/${encodeSeg(projectId)}/treatments/${encodeSeg(input.treatment_id)}/confirm`,
        { method: "POST", body: { production_pack_id: input.production_pack_id ?? null } },
      ),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      inv.invalidateFromTreatment(projectId);
    },
  });
}

export function useGenerateScreenplay(projectId: string) {
  const inv = useInvalidator();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<ScreenplayPackage>(`/api/projects/${encodeSeg(projectId)}/screenplay/generate`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.screenplay(projectId), data);
      inv.invalidateProject(projectId);
    },
  });
}

export function useGenerateShots(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: () =>
      apiJson<ShotSpec[]>(`/api/projects/${encodeSeg(projectId)}/shots/generate`, { method: "POST" }),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      inv.invalidateFromShot(projectId);
    },
  });
}

export function useUpdateShot(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (input: { shot_id: string; updates: Record<string, unknown> }) =>
      apiJson<ShotSpec>(
        `/api/projects/${encodeSeg(projectId)}/shots/${encodeSeg(input.shot_id)}`,
        { method: "PATCH", body: { updates: input.updates } },
      ),
    onSuccess: () => {
      inv.invalidateFromShot(projectId);
    },
  });
}

export function useConfirmShots(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: () =>
      apiJson<{ status: string }>(`/api/projects/${encodeSeg(projectId)}/shots/confirm`, { method: "POST" }),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      void inv;
    },
  });
}

export function useCompilePackages(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiJson<PackagesResponse>(`/api/projects/${encodeSeg(projectId)}/packages/generate`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.packages(projectId), data);
    },
  });
}

export function useRenderShot(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: (shotId: string) =>
      apiJson<RenderRun>(`/api/shots/${encodeSeg(shotId)}/render`, {
        method: "POST",
        body: { project_id: projectId },
      }),
    onSuccess: () => {
      inv.invalidateProject(projectId);
    },
  });
}

export function useRenderAll(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: () =>
      apiJson<RenderRun[]>(`/api/projects/${encodeSeg(projectId)}/render_all`, { method: "POST" }),
    onSuccess: () => {
      inv.invalidateProject(projectId);
      void inv;
    },
  });
}

export function useCreateRoughCut(projectId: string) {
  const inv = useInvalidator();
  return useMutation({
    mutationFn: () =>
      apiJson<{ status: string; download_url: string }>(
        `/api/projects/${encodeSeg(projectId)}/rough_cut`,
        { method: "POST" },
      ),
    onSuccess: () => {
      inv.invalidateProject(projectId);
    },
  });
}
