// Frontend registry of report modules. Add an entry here (plus a dashboard page + route) for each new backend module.
export interface ModuleInfo { key: string; title: string; heading: string; route: string }

export const MODULES: ModuleInfo[] = [
  { key: "container_loading", title: "Container Loading Monitoring", heading: "CONTAINER LOADING MONITORING", route: "/" },
  { key: "production_supervision", title: "Production Supervision", heading: "PRODUCTION SUPERVISION", route: "/production" },
  { key: "pre_shipment", title: "Pre-Shipment Inspection", heading: "PRE-SHIPMENT INSPECTION", route: "/preshipment" },
];

export const moduleByKey = (key: string) => MODULES.find((m) => m.key === key) ?? MODULES[0];
export const moduleByPath = (path: string) => MODULES.find((m) => m.route !== "/" && path.startsWith(m.route)) ?? MODULES[0];
