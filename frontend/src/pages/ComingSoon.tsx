import { NavLink } from "react-router-dom";

/** Placeholder for menu items whose report type has no template/dashboard yet. */
export default function ComingSoon({ title, note }: { title: string; note: string }) {
  return (
    <div className="card coming-soon">
      <h2>{title}</h2>
      <p>{note}</p>
      <p className="muted">
        Each report type gets its own dashboard, upload and report export once its Word template is available.
        Meanwhile you can use <NavLink to="/production">Production Supervision</NavLink>, <NavLink to="/preshipment">Pre-Shipment Inspection</NavLink> or{" "}
        <NavLink to="/containerLoadingCheck">Container Loading Check</NavLink>.
      </p>
    </div>
  );
}
