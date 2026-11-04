import { useSimpleDashboard } from "../components/simple";
import { DataTable, Kpi, Panel, TrendChart } from "../components/widgets";

const MODULE = "pre_production_audit";

export default function AuditDashboard() {
  const { w, has, filters, status } = useSimpleDashboard(MODULE);
  return (
    <div className="dashboard">
      {filters}
      {status("Pre-Production Audit")}
      <div className="kpis">
        {(["kpi_ppa_audits", "kpi_ppa_checks", "kpi_ppa_nc", "kpi_ppa_open"] as const).map((k) => has(k) && <Kpi key={k} id={k} data={w[k]} />)}
      </div>
      <div className="row two">
        {has("ppa_nc_trend") && <Panel title="Non-Conformities by Date of Finding"><TrendChart data={w.ppa_nc_trend} grouped /></Panel>}
        {has("ppa_audits") && <Panel title="Audits"><DataTable data={w.ppa_audits} /></Panel>}
      </div>
      {has("ppa_sections") && <div className="row"><Panel title="Readiness by Section"><DataTable data={w.ppa_sections} /></Panel></div>}
      {has("ppa_nonconformities") && <div className="row"><Panel title="Non-Conformities"><DataTable data={w.ppa_nonconformities} /></Panel></div>}
      {has("ppa_checks") && <div className="row"><Panel title="Readiness Checklist"><DataTable data={w.ppa_checks} /></Panel></div>}
    </div>
  );
}
