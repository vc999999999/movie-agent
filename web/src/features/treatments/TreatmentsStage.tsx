import { useMemo, useState } from "react";
import {
  useConfirmTreatment,
  useGenerateTreatments,
  useProject,
  useTreatments,
} from "../../api/queries";
import type { TreatmentOption } from "../../api/types";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { ErrorNotice } from "../../components/ErrorNotice";
import { StageFooter } from "../../components/StageFooter";
import { StatusBadge } from "../../components/StatusBadge";
import { useNextStage } from "../../components/nextStage";
import { useToast } from "../../components/Toast";
import { useInspector } from "../../app/App";

const RISK_LABEL: Record<TreatmentOption["production_risk"], { label: string; tone: "success" | "warning" | "danger" }> = {
  low: { label: "风险低", tone: "success" },
  medium: { label: "风险中", tone: "warning" },
  high: { label: "风险高", tone: "danger" },
};

function TreatmentCard({
  option,
  recommended,
  diffOnly,
  onConfirm,
  confirming,
}: {
  option: TreatmentOption;
  recommended: boolean;
  diffOnly: boolean;
  onConfirm: (option: TreatmentOption) => void;
  confirming: boolean;
}) {
  const risk = RISK_LABEL[option.production_risk];
  const row = (label: string, value: React.ReactNode) => (
    <div style={{ display: "grid", gap: 3 }}>
      <span className="text-tertiary" style={{ fontSize: 11 }}>{label}</span>
      <span style={{ fontSize: 13, lineHeight: 1.6 }}>{value}</span>
    </div>
  );
  return (
    <article
      className="card"
      style={{
        padding: 18,
        display: "grid",
        gap: 12,
        alignContent: "start",
        borderColor: recommended ? "rgb(200 169 107 / 55%)" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h3 className="display" style={{ fontSize: 16 }}>{option.name}</h3>
        {recommended ? <StatusBadge tone="accent" label="导演推荐" /> : null}
        <StatusBadge tone={risk.tone} label={risk.label} />
        <span className="tag mono" style={{ fontSize: 11 }}>约 {option.estimated_shots} 镜头</span>
      </div>
      {!diffOnly ? (
        <>
          {row("核心问题", option.core_question)}
          {row("Logline", option.logline)}
        </>
      ) : null}
      {row("结构", option.structure)}
      {!diffOnly ? row("视觉策略", option.visual_strategy) : null}
      {option.technique_plan.length > 0
        ? row(
            "名导技法计划",
            <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {option.technique_plan.map((t) => (
                <span key={t} className="tag" style={{ fontSize: 11 }}>{t}</span>
              ))}
            </span>,
          )
        : null}
      {!diffOnly && option.viewer_effect ? row("预期观众感受", option.viewer_effect) : null}
      <div style={{ marginTop: "auto", paddingTop: 8 }}>
        <Button variant={recommended ? "primary" : "secondary"} onClick={() => onConfirm(option)} disabled={confirming} style={{ width: "100%" }}>
          {confirming ? "确认中…" : "选择此方案"}
        </Button>
      </div>
    </article>
  );
}

export function TreatmentsStage({ projectId }: { projectId: string }) {
  const projectQuery = useProject(projectId);
  const status = projectQuery.data?.project.status;
  const treatmentsQuery = useTreatments(projectId, true);
  const generateTreatments = useGenerateTreatments(projectId);
  const confirmTreatment = useConfirmTreatment(projectId);
  const [diffOnly, setDiffOnly] = useState(false);
  const [pendingOption, setPendingOption] = useState<TreatmentOption | null>(null);
  const { toast } = useToast();
  const onNextStage = useNextStage("treatments");

  const pkg = treatmentsQuery.data ?? null;
  const hasTreatments = pkg !== null && pkg.options.length > 0;
  const alreadyConfirmed = status !== "treatment_review" && status !== undefined;

  const recommended = useMemo(
    () => pkg?.options.find((o) => o.treatment_id === pkg.recommendation) ?? null,
    [pkg],
  );

  useInspector(
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ fontSize: 14 }}>方案上下文</h3>
      {pkg ? (
        <>
          <p className="text-secondary" style={{ fontSize: 12 }}>
            共 {pkg.options.length} 个导演方案
            {recommended ? `，推荐「${recommended.name}」` : ""}。
          </p>
          {pkg.recommendation_reason ? (
            <div>
              <div className="text-tertiary" style={{ fontSize: 12, marginBottom: 4 }}>推荐理由</div>
              <p className="text-secondary" style={{ fontSize: 12, lineHeight: 1.7 }}>{pkg.recommendation_reason}</p>
            </div>
          ) : null}
          <p className="text-tertiary" style={{ fontSize: 12 }}>
            确认方案后将生成剧本与分镜；此操作会使已有下游产物失效。
          </p>
        </>
      ) : (
        <p className="text-tertiary" style={{ fontSize: 12 }}>生成 2-3 个导演方案后，这里会显示推荐理由与风险。</p>
      )}
    </div>,
    [pkg, recommended],
  );

  const doConfirm = () => {
    if (!pendingOption || confirmTreatment.isPending) return;
    confirmTreatment.mutate(
      { treatment_id: pendingOption.treatment_id, production_pack_id: pendingOption.production_pack_id },
      {
        onSuccess: () => {
          setPendingOption(null);
          toast("导演方案已确认，剧本与分镜已生成", "success");
        },
      },
    );
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <header style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div>
          <h2 className="display" style={{ fontSize: 22 }}>导演方案对比</h2>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 6 }}>
            每个方案回答同一个创意，但选择不同的结构、风险与技法路径。
          </p>
        </div>
        <span style={{ flex: 1 }} />
        {hasTreatments ? (
          <button
            type="button"
            className={`tag hover-lift ${diffOnly ? "tag-accent" : ""}`}
            onClick={() => setDiffOnly((v) => !v)}
            aria-pressed={diffOnly}
          >
            {diffOnly ? "显示完整方案" : "只看差异"}
          </button>
        ) : null}
      </header>

      {treatmentsQuery.isLoading ? <p className="text-tertiary" aria-live="polite">正在载入方案…</p> : null}

      {!hasTreatments && !treatmentsQuery.isLoading ? (
        <div className="card" style={{ padding: 24, display: "grid", gap: 12, maxWidth: 520 }}>
          <p className="text-secondary" style={{ fontSize: 14 }}>
            还没有导演方案。基于当前创作简报生成 2-3 个可比较的方案。
          </p>
          {generateTreatments.isError ? (
            <ErrorNotice title="生成方案失败" impact="简报未修改，可重试。" error={generateTreatments.error} />
          ) : null}
          <div>
            <Button
              variant="primary"
              onClick={() => generateTreatments.mutate()}
              disabled={generateTreatments.isPending}
            >
              {generateTreatments.isPending ? "正在生成方案…" : "生成导演方案"}
            </Button>
          </div>
        </div>
      ) : null}

      {hasTreatments ? (
        <div
          style={{
            display: "grid",
            gap: 14,
            gridTemplateColumns: `repeat(${Math.min(pkg.options.length, 3)}, minmax(0, 1fr))`,
          }}
          className="treatments-grid"
        >
          {pkg.options.map((option) => (
            <TreatmentCard
              key={option.treatment_id}
              option={option}
              recommended={option.treatment_id === pkg.recommendation}
              diffOnly={diffOnly}
              onConfirm={setPendingOption}
              confirming={confirmTreatment.isPending}
            />
          ))}
        </div>
      ) : null}

      {hasTreatments && !alreadyConfirmed ? (
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            variant="ghost"
            onClick={() => generateTreatments.mutate()}
            disabled={generateTreatments.isPending}
          >
            {generateTreatments.isPending ? "正在重新生成…" : "重新生成方案"}
          </Button>
        </div>
      ) : null}

      <StageFooter
        done={alreadyConfirmed}
        hasNext
        nextLabel="剧本圣经"
        onNext={onNextStage}
      />

      <Dialog open={pendingOption !== null} onClose={() => setPendingOption(null)} title="确认导演方案">
        {pendingOption ? (
          <div style={{ display: "grid", gap: 14 }}>
            <p style={{ fontSize: 14 }}>
              确认采用「<strong>{pendingOption.name}</strong>」？Agent 将按此方案生成剧本与分镜，已有的下游产物会被替换。
            </p>
            {confirmTreatment.isError ? (
              <ErrorNotice title="确认方案失败" error={confirmTreatment.error} />
            ) : null}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <Button variant="ghost" onClick={() => setPendingOption(null)}>再想想</Button>
              <Button variant="primary" onClick={doConfirm} disabled={confirmTreatment.isPending}>
                {confirmTreatment.isPending ? "正在生成剧本与分镜…" : "确认采用"}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}
