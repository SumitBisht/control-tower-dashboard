import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { DataTable, Kpi, Panel, TrendChart } from "../components/widgets";

const MODULE = "pre_shipment";
const FILTERS = [
  { key: "spv", label: "SPV Name" },
  { key: "project", label: "Project Name" },
  { key: "manufacturer", label: "Manufacturer" },
  { key: "lot", label: "Lot" },
] as const;
const TITLES: Record<string, string> = {
  lot_sizes: "Lot Size by Lot (modules)",
  lots: "Lots Inspected",
  results: "Inspection Result Summary",
  nonconformities: "Non-Conformities",
  max_power: "Maximum Power Determination (pre vs during PDI)",
  equipment: "Test Equipment & Calibration",
};

export default function PreShipmentDashboard() {
  const [sel, setSel] = useState<Record<string, string>>({});
  const opts = useQuery({ queryKey: ["psi-filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const qs = new URLSearchParams(Object.entries(sel).filter(([, v]) => v && v !== "All")).toString();
  const dash = useQuery({ queryKey: ["psi-dashboard", qs], queryFn: () => api<{ widgets: Record<string, any> }>(`/${MODULE}/dashboard?${qs}`) });
  const w = dash.data?.widgets ?? {};
  const has = (k: string) => k in w;
  const set = (k: string, v: string) => setSel({ ...sel, [k]: v });
  const noData = dash.data && !opts.isLoading && (opts.data?.lot ?? []).length === 0;

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
        <label><span>Report date from</span><input type="date" value={sel.date_from ?? ""} max={sel.date_to || undefined} onChange={(e) => set("date_from", e.target.value)} /></label>
        <label><span>Report date to</span><input type="date" value={sel.date_to ?? ""} min={sel.date_from || undefined} onChange={(e) => set("date_to", e.target.value)} /></label>
      </div>

      {dash.isError && <div className="alert error">{(dash.error as Error).message}</div>}
      {dash.isLoading && <div className="center-msg">Loading…</div>}
      {noData && <div className="alert info">No Pre-Shipment Inspection reports yet. An uploader can add them under Upload Master.</div>}
      {dash.data && Object.keys(w).length === 0 && <div className="empty">All widgets are hidden. An administrator can enable them under Widgets &amp; Columns.</div>}

      <div className="kpis">
        {(["kpi_lots", "kpi_pass_rate", "kpi_ncs", "kpi_power_dev"] as const).map((k) => has(k) && <Kpi key={k} id={k} data={w[k]} />)}
      </div>
      <div className="row two">
        {has("lot_sizes") && <Panel title={TITLES.lot_sizes}><TrendChart data={w.lot_sizes} /></Panel>}
        {has("lots") && <Panel title={TITLES.lots}><DataTable data={w.lots} /></Panel>}
      </div>
      {has("results") && <div className="row"><Panel title={TITLES.results}><DataTable data={w.results} /></Panel></div>}
      <div className="row two">
        {has("nonconformities") && <Panel title={TITLES.nonconformities}><DataTable data={w.nonconformities} /></Panel>}
        {has("max_power") && <Panel title={TITLES.max_power}><DataTable data={w.max_power} /></Panel>}
      </div>
      {has("equipment") && <div className="row"><Panel title={TITLES.equipment}><DataTable data={w.equipment} /></Panel></div>}
    </div>
  );
}
