import { useQuery } from "@tanstack/react-query";
import { FormEvent, ReactNode, useState } from "react";
import { api, download } from "../api";
import { fmtCell } from "./widgets";

/** Shared dashboard + Report Master pieces for the one-document-per-report modules (BOM Assessment, Pre-Production Audit). */
const FILTERS = [{ key: "spv", label: "SPV Name" }, { key: "project", label: "Project Name" }, { key: "manufacturer", label: "Manufacturer" }] as const;
const query = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v && v !== "All")).toString();

export function useSimpleDashboard(module: string) {
  const [sel, setSel] = useState<Record<string, string>>({});
  const opts = useQuery({ queryKey: ["simple-filters", module], queryFn: () => api<Record<string, string[]>>(`/${module}/filters`) });
  const qs = query(sel);
  const dash = useQuery({ queryKey: ["simple-dashboard", module, qs], queryFn: () => api<{ widgets: Record<string, any> }>(`/${module}/dashboard?${qs}`) });
  const w = dash.data?.widgets ?? {};
  const filters = (
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
      <label><span>Report date from</span><input type="date" value={sel.date_from ?? ""} max={sel.date_to || undefined} onChange={(e) => setSel({ ...sel, date_from: e.target.value })} /></label>
      <label><span>Report date to</span><input type="date" value={sel.date_to ?? ""} min={sel.date_from || undefined} onChange={(e) => setSel({ ...sel, date_to: e.target.value })} /></label>
    </div>
  );
  const status = (what: string) => (
    <>
      {dash.isError && <div className="alert error">{(dash.error as Error).message}</div>}
      {dash.isLoading && <div className="center-msg">Loading…</div>}
      {dash.data && !opts.isLoading && (opts.data?.project ?? []).length === 0 && <div className="alert info">No {what} reports yet. An uploader can add them under Upload Master.</div>}
      {dash.data && Object.keys(w).length === 0 && <div className="empty">All widgets are hidden. An administrator can enable them under Widgets &amp; Columns.</div>}
    </>
  );
  return { w, has: (k: string) => k in w, filters, status };
}

export interface ReportColumn { label: string; cell: (r: any) => ReactNode }

export function SimpleReports({ module, exportName, hint, columns }: { module: string; exportName: string; hint: string; columns: ReportColumn[] }) {
  const EMPTY = { date_from: "", date_to: "", spv: "", project: "", manufacturer: "", q: "" };
  const [form, setForm] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const opts = useQuery({ queryKey: ["simple-filters", module], queryFn: () => api<Record<string, string[]>>(`/${module}/filters`) });
  const res = useQuery({ queryKey: ["simple-reports", module, query(applied)], queryFn: () => api<{ total: number; items: any[] }>(`/${module}/reports?${query(applied)}`) });
  const items = res.data?.items ?? [];

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const search = (e: FormEvent) => { e.preventDefault(); setMsg(null); setApplied(form); };
  const run = async (fmt: "xlsx" | "csv") => {
    setBusy(fmt);
    setMsg(null);
    try { await download(`/${module}/reports/export?format=${fmt}&${query(applied)}`, `${exportName}.${fmt}`); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(null); }
  };
  const select = (k: "spv" | "project" | "manufacturer", label: string) => (
    <label>{label}
      <select value={form[k]} onChange={set(k)}><option value="">All</option>{(opts.data?.[k] ?? []).map((o) => <option key={o}>{o}</option>)}</select>
    </label>
  );

  return (
    <div>
      <form className="card" onSubmit={search}>
        <div className="form-row">
          <label>Report date from<input type="date" value={form.date_from} max={form.date_to || undefined} onChange={set("date_from")} /></label>
          <label>Report date to<input type="date" value={form.date_to} min={form.date_from || undefined} onChange={set("date_to")} /></label>
          {select("manufacturer", "Manufacturer")}
        </div>
        <div className="form-row">
          {select("spv", "SPV")}
          {select("project", "Project")}
          <label>Search<input placeholder="Report no, SPV, project, site…" value={form.q} onChange={set("q")} /></label>
        </div>
        <div className="btn-row">
          <button className="primary">Search</button>
          <button type="button" className="link" onClick={() => { setForm(EMPTY); setApplied(EMPTY); setMsg(null); }}>Reset</button>
          <span className="spacer" />
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("xlsx")}>{busy === "xlsx" ? "Preparing…" : "Export Excel (all sections)"}</button>
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("csv")}>{busy === "csv" ? "Preparing…" : "Export CSV (main table)"}</button>
        </div>
      </form>
      <p className="muted">{hint} Photos in the Word reports are not stored or shown, and the original files are not kept.</p>
      {msg && <div className="alert error">{msg}</div>}
      {res.isError && <div className="alert error">{(res.error as Error).message}</div>}
      <table className="grid">
        <thead><tr>{columns.map((c) => <th key={c.label}>{c.label}</th>)}</tr></thead>
        <tbody>
          {items.map((r) => <tr key={r.id}>{columns.map((c) => <td key={c.label}>{c.cell(r)}</td>)}</tr>)}
          {!res.isLoading && items.length === 0 && <tr><td colSpan={columns.length} className="empty">No reports match these filters.</td></tr>}
        </tbody>
      </table>
      {res.data && <p className="muted">{res.data.total} report(s)</p>}
    </div>
  );
}

export const spvCell = (r: any) => <>{r.spvName}<br /><small className="muted">{r.projectName}</small></>;
export const pill = (key: string, v: any) => fmtCell(key, v);
