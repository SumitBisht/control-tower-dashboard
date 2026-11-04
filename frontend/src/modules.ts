// Frontend registry of report modules. Add an entry here (plus a dashboard page + route) for each new backend module.
export interface ModuleInfo { key: string; title: string; heading: string; route: string }

export const MODULES: ModuleInfo[] = [
  { key: "container_loading", title: "Container Loading Monitoring", heading: "CONTAINER LOADING MONITORING", route: "/containerLoadingCheck" },
  { key: "production_supervision", title: "Production Supervision", heading: "PRODUCTION SUPERVISION", route: "/production" },
  { key: "pre_shipment", title: "Pre-Shipment Inspection", heading: "PRE-SHIPMENT INSPECTION", route: "/preshipment" },
  { key: "pre_production_audit", title: "Pre-Production Audit", heading: "PRE-PRODUCTION AUDIT", route: "/preproductionaudit" },
  { key: "bom_verification", title: "BOM Assessment", heading: "BOM ASSESSMENT", route: "/bomassessment" },
];

export const moduleByKey = (key: string) => MODULES.find((m) => m.key === key) ?? MODULES[0];
export const moduleByPath = (path: string) => MODULES.find((m) => path.startsWith(m.route)) ?? MODULES[0];
