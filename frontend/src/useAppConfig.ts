import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export interface AppConfig { clientName: string; appName: string }

/** Display settings from the server (CLIENT_NAME in .env). Cached for the session. */
export function useAppConfig(): AppConfig {
  const q = useQuery({ queryKey: ["CLIENT_NAME"], queryFn: () => api<AppConfig>("/config"), staleTime: Infinity });
  return q.data ?? { clientName: "DSR", appName: "control panel" };
}
