import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { Checklist, DataTable, Kpi, Panel, TrendChart, WIDGET_TITLES } from "../components/widgets";

const MODULE = "container_loading";
const FILTERS = [
  { key: "spv", label: "SPV Name" },
  { key: "project", label: "Project Name" },
  { key: "manufacturer", label: "Manufacturer" },
  { key: "psi_lot", label: "PSI Lot/s" },
] as const;

export default function Dashboard() {
  const [sel, setSel] = useState<Record<string, string>>({});
  const opts = useQuery({ queryKey: ["filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const qs = new URLSearchParams(Object.entries(sel).filter(([, v]) => v && v !== "All")).toString();
  const dash = useQuery({ queryKey: ["dashboard", qs], queryFn: () => api<{ widgets: Record<string, any> }>(`/${MODULE}/dashboard?${qs}`) });
  const w = dash.data?.widgets ?? {};
  const has = (k: string) => k in w;

  return (
    <div className="dashboard">
      <div className="filters">
        {FILTERS.map((f) => (
          <label key={f.key}>
            <span>{f.label}</span>
            <select value={sel[f.key] ?? "All"} onChange={(e) => setSel({ ...sel, [f.key]: e.target.value })}>
              <option>All</option>
              {(opts.data?.[f.key] ?? []).map((o) => <option key={o}>{o}</option>)}
            </select>
          </label>
        ))}
      </div>

      {dash.isError && <div className="alert error">{(dash.error as Error).message}</div>}
      {dash.isLoading && <div className="center-msg">Loading…</div>}
      {dash.data && Object.keys(w).length === 0 && <div className="empty">All widgets are hidden. An administrator can enable them under Widgets &amp; Columns.</div>}

      <div className="kpis">
        {(["kpi_containers", "kpi_modules", "kpi_capacity", "kpi_result"] as const).map((k) => has(k) && <Kpi key={k} id={k} data={w[k]} />)}
      </div>
      <div className="row two">
        {has("loading_trend") && <Panel title={WIDGET_TITLES.loading_trend}><TrendChart data={w.loading_trend} /></Panel>}
        {has("product_summary") && <Panel title={WIDGET_TITLES.product_summary}><DataTable data={w.product_summary} /></Panel>}
      </div>
      <div className="row two">
        {has("recent_containers") && <Panel title={WIDGET_TITLES.recent_containers}><DataTable data={w.recent_containers} /></Panel>}
        {has("checklist_summary") && <Panel title={WIDGET_TITLES.checklist_summary}><Checklist data={w.checklist_summary} /></Panel>}
      </div>
    </div>
  );
}
