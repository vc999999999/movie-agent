import { useQuery } from "@tanstack/react-query";
import { apiJson } from "../api/client";
export function DemoNotice() {
  const query = useQuery({ queryKey: ["capabilities"], queryFn: () => apiJson<{demo_mode: boolean}>("/api/capabilities"), staleTime: Infinity });
  return query.data?.demo_mode ? <span className="tag" title="剧情生成为测试数据">演示模式</span> : null;
}
