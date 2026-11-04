import { pill, ReportColumn, SimpleReports, spvCell } from "../components/simple";

const COLUMNS: ReportColumn[] = [
  { label: "Report No", cell: (r) => <b>{r.reportNo}</b> },
  { label: "Report date", cell: (r) => r.reportDate },
  { label: "SPV / Project", cell: spvCell },
  { label: "Manufacturer", cell: (r) => r.manufacturer },
  { label: "Audit date", cell: (r) => r.auditDate ?? "—" },
  { label: "Checks closed", cell: (r) => `${r.checksClosed} / ${r.checks}` },
  { label: "Non-conformities", cell: (r) => `${r.ncTotal} (${r.ncOpen} open)` },
  { label: "Conclusion", cell: (r) => pill("conclusion", r.conclusion) },
];

export default function AuditReports() {
  return <SimpleReports module="pre_production_audit" exportName="pre-production-audit" columns={COLUMNS}
    hint="The Excel export has one sheet per section (readiness checklist, audit reports, non-conformities)." />;
}
