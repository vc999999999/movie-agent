import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        // Retry once only for network-level failures, not API errors.
        return !(error instanceof Error && error.name === "ApiError");
      },
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});
