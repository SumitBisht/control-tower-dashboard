import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { DataTable, Kpi, Panel, TrendChart } from "../components/widgets";

const MODULE = "production_supervision";
const FILTERS = [
  { key: "spv", label: "SPV Name" },
  { key: "project", label: "Project Name" },
  { key: "manufacturer", label: "Manufacturer" },
  { key: "power_bin", label: "Power Bin (Wp)" },
] as const;
const TITLES: Record<string, string> = {
  production_trend: "Planned vs Actual Output",
  daily_production: "Daily Production",
  qualification: "Qualified & Rejected Modules",
  nonconformities: "Non-Conformities",
  quality_checks: "Quality Checks",
};

export default function ProductionDashboard() {
  const [sel, setSel] = useState<Record<string, string>>({});
  const opts = useQuery({ queryKey: ["ps-filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const qs = new URLSearchParams(Object.entries(sel).filter(([, v]) => v && v !== "All")).toString();
  const dash = useQuery({ queryKey: ["ps-dashboard", qs], queryFn: () => api<{ widgets: Record<string, any> }>(`/${MODULE}/dashboard?${qs}`) });
  const w = dash.data?.widgets ?? {};
  const has = (k: string) => k in w;
  const set = (k: string, v: string) => setSel({ ...sel, [k]: v });
  const noData = dash.data && !opts.isLoading && (opts.data?.spv ?? []).length === 0;

  return (
    <div className="dashboard">
      <div className="filters">
        {FILTERS.map((f) => (
          <label key={f.key}>
            <span>{f.label}</span>
            <select value={sel[f.key] ?? "All"} onChange={(e) => set(f.key, e.target.value)}>
              <option>All</option>
              {(opts.data?.[f.key] ?? []).map((o) => <option key={o}>{o}</option>)}
            </select>
          </label>
        ))}
        <label><span>Production from</span><input type="date" value={sel.date_from ?? ""} max={sel.date_to || undefined} onChange={(e) => set("date_from", e.target.value)} /></label>
        <label><span>Production to</span><input type="date" value={sel.date_to ?? ""} min={sel.date_from || undefined} onChange={(e) => set("date_to", e.target.value)} /></label>
      </div>

      {dash.isError && <div className="alert error">{(dash.error as Error).message}</div>}
      {dash.isLoading && <div className="center-msg">Loading…</div>}
      {noData && <div className="alert info">No Production Supervision reports yet. An uploader can add them under Upload Master.</div>}
      {dash.data && Object.keys(w).length === 0 && <div className="empty">All widgets are hidden. An administrator can enable them under Widgets &amp; Columns.</div>}

      <div className="kpis">
        {(["kpi_output", "kpi_achievement", "kpi_rejected", "kpi_open_nc"] as const).map((k) => has(k) && <Kpi key={k} id={k} data={w[k]} />)}
      </div>
      <div className="row two">
        {has("production_trend") && <Panel title={TITLES.production_trend}><TrendChart data={w.production_trend} /></Panel>}
        {has("daily_production") && <Panel title={TITLES.daily_production}><DataTable data={w.daily_production} /></Panel>}
      </div>
      <div className="row two">
        {has("qualification") && <Panel title={TITLES.qualification}><DataTable data={w.qualification} /></Panel>}
        {has("quality_checks") && (
          <Panel title={`${TITLES.quality_checks}${w.quality_checks.source ? ` — ${w.quality_checks.source}` : ""}`}>
            <DataTable data={w.quality_checks} />
          </Panel>
        )}
      </div>
      {has("nonconformities") && <div className="row"><Panel title={TITLES.nonconformities}><DataTable data={w.nonconformities} /></Panel></div>}
    </div>
  );
}
