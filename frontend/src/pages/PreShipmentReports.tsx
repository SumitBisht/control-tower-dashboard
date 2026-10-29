import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api, download } from "../api";
import { fmtCell } from "../components/widgets";

const MODULE = "pre_shipment";
const EMPTY = { date_from: "", date_to: "", spv: "", project: "", manufacturer: "", lot: "", q: "" };
type Filters = typeof EMPTY;

interface Row {
  id: string; reportNo: string; reportDate: string | null; spvName: string; projectName: string; manufacturer: string; workshop: string;
  lotNo: string; lotSizePcs: number | null; lotSizeMwp: number | null; tests: number; testsPassed: number; testsFailed: number;
  ncTotal: number; conclusion: string | null;
}

const qs = (f: Filters) => new URLSearchParams(Object.entries(f).filter(([, v]) => v && v !== "All")).toString();

export default function PreShipmentReports() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const opts = useQuery({ queryKey: ["psi-filters"], queryFn: () => api<Record<string, string[]>>(`/${MODULE}/filters`) });
  const res = useQuery({ queryKey: ["psi-reports", qs(applied)], queryFn: () => api<{ total: number; items: Row[] }>(`/${MODULE}/reports?${qs(applied)}`) });
  const items = res.data?.items ?? [];

  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const search = (e: FormEvent) => { e.preventDefault(); setMsg(null); setApplied(form); };
  const run = async (key: string, fmt: "xlsx" | "csv") => {
    setBusy(key);
    setMsg(null);
    try { await download(`/${MODULE}/reports/export?format=${fmt}&${qs(applied)}`, `pre-shipment.${fmt}`); }
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
          <label>Report date from<input type="date" value={form.date_from} max={form.date_to || undefined} onChange={set("date_from")} /></label>
          <label>Report date to<input type="date" value={form.date_to} min={form.date_from || undefined} onChange={set("date_to")} /></label>
          {select("lot", "Lot", opts.data?.lot)}
          {select("manufacturer", "Manufacturer", opts.data?.manufacturer)}
        </div>
        <div className="form-row">
          {select("spv", "SPV", opts.data?.spv)}
          {select("project", "Project", opts.data?.project)}
          <label>Search<input placeholder="Report no, lot, SPV, project…" value={form.q} onChange={set("q")} /></label>
        </div>
        <div className="btn-row">
          <button className="primary">Search</button>
          <button type="button" className="link" onClick={() => { setForm(EMPTY); setApplied(EMPTY); setMsg(null); }}>Reset</button>
          <span className="spacer" />
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("xlsx", "xlsx")}>
            {busy === "xlsx" ? "Preparing…" : "Export Excel (all sections)"}</button>
          <button type="button" className="primary" disabled={!items.length || busy !== null} onClick={() => run("csv", "csv")}>
            {busy === "csv" ? "Preparing…" : "Export CSV (results)"}</button>
        </div>
      </form>
      <p className="muted">
        The Excel export has one sheet per section (results, non-conformities, equipment, maximum power per module, sun-simulator checks, insulation,
        wet leakage, bi-faciality, mechanical loads, low irradiance…). Photos in the Word reports are not stored or shown, and the original files are not kept.
      </p>
      {msg && <div className="alert error">{msg}</div>}
      {res.isError && <div className="alert error">{(res.error as Error).message}</div>}
      <table className="grid">
        <thead><tr><th>Report No</th><th>Report date</th><th>SPV / Project</th><th>Manufacturer</th><th>Lot</th><th>Lot size</th><th>MWp</th><th>Tests passed</th>
          <th>Non-conformities</th><th>Conclusion</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td><b>{r.reportNo}</b></td><td>{r.reportDate}</td>
              <td>{r.spvName}<br /><small className="muted">{r.projectName}</small></td><td>{r.manufacturer}</td>
              <td>{r.lotNo}</td><td>{r.lotSizePcs?.toLocaleString() ?? "—"}</td><td>{r.lotSizeMwp ?? "—"}</td>
              <td>{r.testsPassed} / {r.tests}</td><td>{r.ncTotal}</td><td>{fmtCell("conclusion", r.conclusion)}</td>
            </tr>
          ))}
          {!res.isLoading && items.length === 0 && <tr><td colSpan={10} className="empty">No reports match these filters.</td></tr>}
        </tbody>
      </table>
      {res.data && <p className="muted">{res.data.total} report(s)</p>}
    </div>
  );
}
