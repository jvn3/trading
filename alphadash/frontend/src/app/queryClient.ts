import { QueryClient } from "@tanstack/react-query";

// TanStack Query owns all server state (blueprint §11.1). Market data uses a short staleTime with
// background refetch; account/journal data can override with longer values per-query.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
