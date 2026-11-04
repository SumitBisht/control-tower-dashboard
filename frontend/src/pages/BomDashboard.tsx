import { useSimpleDashboard } from "../components/simple";
import { DataTable, Kpi, Panel, TrendChart } from "../components/widgets";

const MODULE = "bom_verification";

export default function BomDashboard() {
  const { w, has, filters, status } = useSimpleDashboard(MODULE);
  return (
    <div className="dashboard">
      {filters}
      {status("BOM verification")}
      <div className="kpis">
        {(["kpi_bom_reports", "kpi_bom_pass", "kpi_bom_deviations", "kpi_bom_storage"] as const).map((k) => has(k) && <Kpi key={k} id={k} data={w[k]} />)}
      </div>
      <div className="row two">
        {has("bom_results") && <Panel title="Material Results by Verification"><TrendChart data={w.bom_results} /></Panel>}
        {has("bom_reports") && <Panel title="Verification Reports"><DataTable data={w.bom_reports} /></Panel>}
      </div>
      {has("bom_materials") && <div className="row"><Panel title="Bill of Materials Verification (BOM vs actual)"><DataTable data={w.bom_materials} /></Panel></div>}
      {has("bom_storage") && <div className="row"><Panel title="Materials Storage Conditions"><DataTable data={w.bom_storage} /></Panel></div>}
    </div>
  );
}
