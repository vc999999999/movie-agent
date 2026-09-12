import type { ReactNode } from "react";
import { Button } from "./Button";

interface StageFooterProps {
  /** 当前阶段是否已完成（完成才显示下一步） */
  done: boolean;
  /** 是否还有下一个阶段 */
  hasNext: boolean;
  nextLabel: string;
  onNext: () => void;
  /** 额外操作（如"重新生成"）放在左侧 */
  extra?: ReactNode;
}

/**
 * 阶段底部引导: 完成当前阶段后出现「下一步」按钮，把用户送到下一个阶段，
 * 避免确认后只弹 toast 的死胡同。
 */
export function StageFooter({ done, hasNext, nextLabel, onNext, extra }: StageFooterProps) {
  if (!done || !hasNext) return null;
  return (
    <footer style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
      {extra}
      <span style={{ flex: 1 }} />
      <span className="text-tertiary" style={{ fontSize: 12 }}>
        本阶段已完成，可随时回来调整
      </span>
      <Button variant="primary" onClick={onNext}>
        下一步：{nextLabel} →
      </Button>
    </footer>
  );
}
