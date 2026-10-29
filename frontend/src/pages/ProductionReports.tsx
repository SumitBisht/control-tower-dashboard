import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api, download } from "../api";

const MODULE = "production_supervision";
const EMPTY = { date_from: "", date_to: "", spv: "", project: "", manufacturer: "", q: "" };
type Filters = typeof EMPTY;

interface Row {
  id: string; reportNo: string; reportDate: string | null; spvName: string; projectName: string; manufacturer: string; workshop: string;
  firstDate: string | null; lastDate: string | null; days: number; plannedQty: number; actualQty: number; actualMwp: number;
  rejectedQty: number | null; suspectedQty: number | null; openNcs: number; bomDiffer: number; ipqcFail: number;
}

const qs = (f: Filters) => new URLSearchParams(Object.entries(f).filter(([, v]) => v && v !== "All")).toString();
const n = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString());

export default function ProductionReports() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const opts = useQuery({ queryKey: ["ps-filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const res = useQuery({ queryKey: ["ps-reports", qs(applied)], queryFn: () => api<{ total: number; items: Row[] }>(`/${MODULE}/reports?${qs(applied)}`) });
  const items = res.data?.items ?? [];

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const search = (e: FormEvent) => { e.preventDefault(); setMsg(null); setApplied(form); };
  const run = async (key: string, fmt: "xlsx" | "csv") => {
    setBusy(key);
    setMsg(null);
    try { await download(`/${MODULE}/reports/export?format=${fmt}&${qs(applied)}`, `production-supervision.${fmt}`); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  };
  const select = (k: keyof Filters, label: string, list?: string[]) => (
    <label>{label}
      <select value={form[k]} onChange={set(k)}><option value="">All</option>{(list ?? []).map((o) => <option key={o}>{o}</option>)}</select>
    </label>
  );

  return (
    <div>
      <form className="card" onSubmit={search}>
        <div className="form-row">
          <label>Production from<input type="date" value={form.date_from} max={form.date_to || undefined} onChange={set("date_from")} /></label>
          <label>Production to<input type="date" value={form.date_to} min={form.date_from || undefined} onChange={set("date_to")} /></label>
          {select("manufacturer", "Manufacturer", opts.data?.manufacturer)}
        </div>
        <div className="form-row">
          {select("spv", "SPV", opts.data?.spv)}
          {select("project", "Project", opts.data?.project)}
          <label>Search<input placeholder="Report no, SPV, project, workshop…" value={form.q} onChange={set("q")} /></label>
        </div>
        <div className="btn-row">
          <button className="primary">Search</button>
          <button type="button" className="link" onClick={() => { setForm(EMPTY); setApplied(EMPTY); setMsg(null); }}>Reset</button>
          <span className="spacer" />
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("xlsx", "xlsx")}>
            {busy === "xlsx" ? "Preparing…" : "Export Excel (all sections)"}</button>
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("csv", "csv")}>
            {busy === "csv" ? "Preparing…" : "Export CSV (production)"}</button>
        </div>
      </form>
      <p className="muted">
        The Excel export has one sheet per section (production, qualification, non-conformities, BOM, storage, IPQC, flasher, tests…) for every report listed.
        Photos and videos in the Word reports are not stored or shown, and the original Word files are not kept.
      </p>
      {msg && <div className="alert error">{msg}</div>}
      {res.isError && <div className="alert error">{(res.error as Error).message}</div>}
      <table className="grid">
        <thead><tr><th>Report No</th><th>Report date</th><th>SPV / Project</th><th>Manufacturer</th><th>Production period</th><th>Planned</th><th>Actual</th>
          <th>MWp</th><th>Rejected</th><th>Suspected</th><th>Open NCs</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><b>{r.reportNo}</b></td><td>{r.reportDate}</td>
              <td>{r.spvName}<br /><small className="muted">{r.projectName}</small></td><td>{r.manufacturer}</td>
              <td>{r.firstDate === r.lastDate ? r.firstDate : `${r.firstDate} → ${r.lastDate}`}<br /><small className="muted">{r.days} day(s)</small></td>
              <td>{n(r.plannedQty)}</td><td>{n(r.actualQty)}</td><td>{r.actualMwp}</td><td>{n(r.rejectedQty)}</td><td>{n(r.suspectedQty)}</td>
              <td><span className={`pill ${r.openNcs ? "nok" : "ok"}`}>{r.openNcs}</span></td>
            </tr>
          ))}
          {!res.isLoading && items.length === 0 && <tr><td colSpan={11} className="empty">No reports match these filters.</td></tr>}
        </tbody>
      </table>
      {res.data && <p className="muted">{res.data.total} report(s)</p>}
    </div>
  );
}
