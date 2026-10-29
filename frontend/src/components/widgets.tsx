import { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export const WIDGET_TITLES: Record<string, string> = {
  loading_trend: "Loading Trend by Date (cumulative modules)",
  product_summary: "Product-wise Summary",
  recent_containers: "Recent Containers Loaded",
  checklist_summary: "Inspection Checklist Summary",
};

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      <div className="panel-body">{children}</div>
    </section>
  );
}

const KPI = {
  kpi_containers: { label: "Total Containers", tone: "blue", fmt: (d: any) => d.value.toLocaleString() },
  kpi_modules: { label: "Total Modules", tone: "green", fmt: (d: any) => d.value.toLocaleString() },
  kpi_capacity: { label: "Total Capacity", tone: "amber", fmt: (d: any) => `${d.value.toLocaleString(undefined, { maximumFractionDigits: 3 })} MWp` },
  kpi_result: { label: "Inspection Result", tone: "teal", fmt: (d: any) => (d.value == null ? "—" : `${d.value}% SUCCESS`) },
  // Production Supervision
  kpi_output: { label: "Total Actual Output", tone: "blue", fmt: (d: any) => `${d.value.toLocaleString()} pcs`, sub: (d: any) => `${d.mwp} MWp` },
  kpi_achievement: { label: "Plan Achievement", tone: "teal", fmt: (d: any) => (d.value == null ? "—" : `${d.value}%`),
    sub: (d: any) => `${d.actual.toLocaleString()} of ${d.planned.toLocaleString()} planned` },
  kpi_rejected: { label: "Rejected / Suspected", tone: "amber", fmt: (d: any) => `${d.value.toLocaleString()} pcs`,
    sub: (d: any) => `${d.rejected.toLocaleString()} rejected · ${d.suspected.toLocaleString()} suspected (cumulative)` },
  kpi_open_nc: { label: "Open Non-Conformities", tone: "green", fmt: (d: any) => `${d.value}`, sub: (d: any) => `${d.total} recorded in total` },
  // Pre-Shipment Inspection
  kpi_lots: { label: "Lots Inspected", tone: "blue", fmt: (d: any) => `${d.value}`, sub: (d: any) => `${d.modules.toLocaleString()} modules · ${d.mwp} MWp` },
  kpi_pass_rate: { label: "Tests Passed", tone: "teal", fmt: (d: any) => (d.value == null ? "—" : `${d.value}%`), sub: (d: any) => `${d.passed} of ${d.tests} tests` },
  kpi_ncs: { label: "Non-Conformities", tone: "amber", fmt: (d: any) => `${d.value}`, sub: (d: any) => `${d.major} major · ${d.minor} minor` },
  kpi_power_dev: { label: "Avg Power Difference", tone: "green", fmt: (d: any) => (d.value == null ? "—" : `${d.value}%`),
    sub: (d: any) => `${d.outOfTolerance} module(s) outside ±1% (pre vs during PDI)` },
} as const;

export function Kpi({ id, data }: { id: keyof typeof KPI; data: any }) {
  const k = KPI[id];
  return (
    <div className={`kpi ${k.tone}`}>
      <div className="kpi-label">{k.label}</div>
      <div className="kpi-value">{k.fmt(data)}</div>
      {id === "kpi_result" && data.inspected > 0 && <div className="kpi-sub">{data.passed} of {data.inspected} containers passed</div>}
      {"sub" in k && <div className="kpi-sub">{(k as any).sub(data)}</div>}
    </div>
  );
}

const PALETTE = ["#17658f", "#5aa9ff", "#2e7d6b", "#e0a030", "#8a63d2"];

export function TrendChart({ data }: { data: { series: string[]; data: any[] } }) {
  if (!data.data.length) return <Empty />;
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data.data}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" />
        <YAxis />
        <Tooltip />
        <Legend />
        {data.series.map((s, i) => <Bar key={s} dataKey={s} stackId="a" fill={PALETTE[i % PALETTE.length]} />)}
      </BarChart>
    </ResponsiveContainer>
  );
}

const Empty = () => <div className="empty">No data for the selected filters.</div>;

export function DataTable({ data }: { data: { columns: { key: string; label: string }[]; rows: any[]; wp_classes?: string[] } }) {
  if (!data.rows.length) return <Empty />;
  // The "by Wp" column is a group: expand it into one sub-column per module class present in the data.
  const cols = data.columns.flatMap((c) =>
    c.key === "containers_by_wp" ? (data.wp_classes ?? []).map((w) => ({ key: `wp:${w}`, label: `${w} Wp` })) : [c]);
  const cell = (r: any, key: string): ReactNode => {
    if (key.startsWith("wp:")) return r.containers_by_wp?.[key.slice(3)] ?? 0;
    return fmtCell(key, r[key]);
  };
  return (
    <table className="grid">
      <thead><tr>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
      <tbody>{data.rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c.key}>{cell(r, c.key)}</td>)}</tr>)}</tbody>
    </table>
  );
}

export function Checklist({ data }: { data: { columns: { key: string }[]; rows: any[] } }) {
  const show = (k: string) => data.columns.some((c) => c.key === k);
  return (
    <table className="grid checklist">
      <tbody>
        {data.rows.map((r) => (
          <tr key={r.item}>
            {show("item") && <td>{r.item}</td>}
            {show("status") && <td><span className={`pill ${r.status.toLowerCase()}`}>{r.status === "NA" ? "N/A" : r.status}</span></td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const fmtQM = (v: { qty: number | null; mwp: number | null }) =>
  `${v.qty == null ? "—" : v.qty.toLocaleString()}${v.mwp == null ? "" : ` · ${v.mwp.toLocaleString(undefined, { maximumFractionDigits: 3 })} MWp`}`;

const PILL: Record<string, string> = { OPEN: "nok", CLOSED: "ok", OK: "ok", NOK: "nok", WARN: "na", NA: "na", UNKNOWN: "na", MAJOR: "nok", MINOR: "na", CRITICAL: "nok",
  PASS: "ok", FAIL: "nok", OVERDUE: "nok" };
const PILL_KEYS = new Set(["status", "severity", "decision", "conclusion", "risk", "category"]);

/** Renders table cells: numbers, {qty,mwp} pairs, {bin: {qty,mwp}} maps and status/severity pills. */
export function fmtCell(key: string, v: any): ReactNode {
  if (v == null || v === "") return "—";
  if (PILL_KEYS.has(key) && typeof v === "string") {
    return <span className={`pill ${PILL[v.toUpperCase()] ?? "na"}`}>{v === "NA" ? "N/A" : v}</span>;
  }
  if (typeof v === "number") return key === "psi_lot" ? v : v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (typeof v === "object") {
    if ("qty" in v) return fmtQM(v);
    return Object.entries(v).map(([bin, q]) => <div key={bin}>{bin} Wp: {fmtQM(q as any)}</div>);
  }
  return v;
}
