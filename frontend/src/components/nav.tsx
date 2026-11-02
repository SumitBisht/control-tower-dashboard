import { ReactNode } from "react";
import { Role } from "../api";

export interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  roles?: Role[];
  group?: string;
  soon?: boolean; // module is planned but has no report/dashboard yet: shows a "Soon" tag and opens a placeholder page
}

const Svg = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

const icons = {
  audit: <Svg><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="m9 14 2 2 4-4" /></Svg>,
  bom: <Svg><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></Svg>,
  production: <Svg><path d="M2 20h20" /><path d="M4 20V9l6 4V9l6 4V4h4v16" /></Svg>,
  shipment: <Svg><path d="M21 8 12 3 3 8v8l9 5 9-5z" /><path d="m3 8 9 5 9-5M12 13v8" /></Svg>,
  container: <Svg><path d="M1 6h13v10H1z" /><path d="M14 9h4l4 4v3h-8z" /><circle cx="6" cy="18" r="2" /><circle cx="18" cy="18" r="2" /></Svg>,
  report: <Svg><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h8" /></Svg>,
  upload: <Svg><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></Svg>,
  users: <Svg><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18.5 14.5a6.5 6.5 0 0 1 3 5.5" /></Svg>,
  widgets: <Svg><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></Svg>,
  chevrons: (open: boolean) => <Svg>{open ? <path d="m11 17-5-5 5-5M18 17l-5-5 5-5" /> : <path d="m13 17 5-5-5-5M6 17l5-5-5-5" />}</Svg>,
};
export const chevrons = icons.chevrons;

// The left-hand menu, in display order. Add future modules/pages here.
export const NAV: NavItem[] = [
  { to: "/preproductionaudit", label: "Pre-Production Audit", icon: icons.audit, soon: true },
  { to: "/bomassessment", label: "BOM Assessment", icon: icons.bom, soon: true },
  { to: "/production", label: "Production Supervision", icon: icons.production },
  { to: "/preshipment", label: "Pre-Shipment Inspection", icon: icons.shipment },
  { to: "/containerLoadingCheck", label: "Container Loading Check", icon: icons.container },
  { to: "/reports", label: "Report Master", icon: icons.report },
  { to: "/uploads", label: "Upload Master", icon: icons.upload, roles: ["uploader", "admin"] },
  { to: "/admin/users", label: "Users", icon: icons.users, roles: ["admin"], group: "Admin" },
  { to: "/admin/widgets", label: "Widgets & Columns", icon: icons.widgets, roles: ["admin"], group: "Admin" },
];

/** Page of the menu that is first and has real content: where "/" lands. */
export const HOME = "/production";

export const headingFor = (pathname: string) => NAV.find((n) => pathname === n.to || pathname.startsWith(n.to + "/"))?.label.toUpperCase() ?? "CONTROL TOWER";
