import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, download, ReportRow } from "../api";
import { MODULES } from "../modules";
import PreShipmentReports from "./PreShipmentReports";
import ProductionReports from "./ProductionReports";

const MODULE = "container_loading";
const EMPTY = { date_from: "", date_to: "", spv: "", project: "", manufacturer: "", model: "", psi_lot: "", q: "" };
type Filters = typeof EMPTY;

const qs = (f: Filters) => new URLSearchParams(Object.entries(f).filter(([, v]) => v && v !== "All")).toString();

function ContainerReports() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const opts = useQuery({ queryKey: ["filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const res = useQuery({ queryKey: ["reports", qs(applied)], queryFn: () => api<{ total: number; items: ReportRow[] }>(`/${MODULE}/reports?${qs(applied)}`) });

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const search = (e: FormEvent) => { e.preventDefault(); setMsg(null); setApplied(form); };
  const reset = () => { setForm(EMPTY); setApplied(EMPTY); setMsg(null); };

  const run = async (key: string, path: string, name: string) => {
    setBusy(key);
    setMsg(null);
    try { await download(path, name); } catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  };
  const select = (k: keyof Filters, label: string, list?: string[]) => (
    <label>{label}
      <select value={form[k]} onChange={set(k)}><option value="">All</option>{(list ?? []).map((o) => <option key={o}>{o}</option>)}</select>
    </label>
  );
  const items = res.data?.items ?? [];

  return (
    <div>
      <form className="card" onSubmit={search}>
        <div className="form-row">
          <label>Loaded from<input type="date" value={form.date_from} max={form.date_to || undefined} onChange={set("date_from")} /></label>
          <label>Loaded to<input type="date" value={form.date_to} min={form.date_from || undefined} onChange={set("date_to")} /></label>
          {select("model", "Product type (model)", opts.data?.model)}
          {select("manufacturer", "Manufacturer", opts.data?.manufacturer)}
        </div>
        <div className="form-row">
          {select("spv", "SPV", opts.data?.spv)}
          {select("project", "Project", opts.data?.project)}
          {select("psi_lot", "PSI lot", opts.data?.psi_lot)}
          <label>Search<input placeholder="Report no, container no, seal no…" value={form.q} onChange={set("q")} /></label>
        </div>
        <div className="btn-row">
          <button className="primary">Search</button>
          <button type="button" className="link" onClick={reset}>Reset</button>
          <span className="spacer" />
          <button type="button" className="primary" disabled={!items.length || busy !== null}
            onClick={() => run("xlsx", `/${MODULE}/reports/export?format=xlsx&${qs(applied)}`, "container-loading.xlsx")}>
            {busy === "xlsx" ? "Preparing…" : "Export Excel"}</button>
          <button type="button" className="primary" disabled={!items.length || busy !== null}
            onClick={() => run("csv", `/${MODULE}/reports/export?format=csv&${qs(applied)}`, "container-loading.csv")}>
            {busy === "csv" ? "Preparing…" : "Export CSV"}</button>
        </div>
      </form>
      <p className="muted">Exports contain one row per container matching the filters above (inspection and checklist results included).</p>
      {msg && <div className="alert error">{msg}</div>}
      {res.isError && <div className="alert error">{(res.error as Error).message}</div>}

      <table className="grid">
        <thead><tr><th>Report No</th><th>Report date</th><th>SPV / Project</th><th>Manufacturer</th><th>Product type</th>
          <th>Loaded</th><th>Containers</th><th>Modules</th><th>MWp</th><th>Result</th><th /></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><b>{r.reportNo}</b></td><td>{r.reportDate}</td>
              <td>{r.spvName}<br /><small className="muted">{r.projectName}</small></td>
              <td>{r.manufacturer}</td><td>{r.models.join(", ")}</td>
              <td>{r.loadingFrom === r.loadingTo ? r.loadingFrom : `${r.loadingFrom} → ${r.loadingTo}`}</td>
              <td>{r.containers}</td><td>{r.modules.toLocaleString()}</td><td>{r.capacityMwp}</td>
              <td><span className={`pill ${r.failedContainers ? "nok" : "ok"}`}>{r.failedContainers ? `${r.failedContainers} failed` : r.conclusion ?? "—"}</span></td>
              <td className="actions">
                {r.hasSource
                  ? <button className="link" disabled={busy !== null} onClick={() => run(r.id, `/${MODULE}/reports/${r.id}/download`, r.sourceFileName ?? `${r.reportNo}.docx`)}>
                      {busy === r.id ? "Downloading…" : "Download .docx"}</button>
                  : <span className="muted">no file</span>}
              </td>
            </tr>
          ))}
          {!res.isLoading && items.length === 0 && <tr><td colSpan={11} className="empty">No reports match these filters.</td></tr>}
        </tbody>
      </table>
      {res.data && <p className="muted">{res.data.total} report(s)</p>}
    </div>
  );
}

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const key = params.get("module") ?? MODULES[0].key;
  return (
    <div>
      <h2>Report Master</h2>
      <label className="inline-select">Report type
        <select value={key} onChange={(e) => setParams({ module: e.target.value })}>{MODULES.map((m) => <option key={m.key} value={m.key}>{m.title}</option>)}</select>
      </label>
      {key === "production_supervision" ? <ProductionReports /> : key === "pre_shipment" ? <PreShipmentReports /> : <ContainerReports />}
    </div>
  );
}
