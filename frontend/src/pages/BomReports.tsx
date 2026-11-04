import { pill, ReportColumn, SimpleReports, spvCell } from "../components/simple";

const COLUMNS: ReportColumn[] = [
  { label: "Report No", cell: (r) => <b>{r.reportNo}</b> },
  { label: "Report date", cell: (r) => r.reportDate },
  { label: "SPV / Project", cell: spvCell },
  { label: "Manufacturer", cell: (r) => r.manufacturer },
  { label: "Materials", cell: (r) => r.materials },
  { label: "Passed", cell: (r) => `${r.passed} / ${r.materials}` },
  { label: "Under review", cell: (r) => r.underReview },
  { label: "BOM deviations", cell: (r) => r.deviations },
  { label: "Storage OK", cell: (r) => `${r.storagePassed} / ${r.storageItems}` },
  { label: "Result", cell: (r) => pill("result", r.failed ? "FAIL" : r.underReview ? "UNDER REVIEW" : "PASS") },
];

export default function BomReports() {
  return <SimpleReports module="bom_verification" exportName="bom-verification" columns={COLUMNS}
    hint="The Excel export has one sheet per section (materials with BOM vs actual, verification reports, storage conditions)." />;
}
