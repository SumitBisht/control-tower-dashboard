import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import logo from "../assets/logo.jpeg";

// Add future modules/pages here. `roles` limits visibility; `soon` renders a disabled placeholder.
const NAV = [
  { to: "/", label: "Container Loading Monitoring", end: true },
  { to: "/reports", label: "Report Master" },
  { to: "/uploads", label: "Upload Master", roles: ["uploader", "admin"] },
  { to: "/admin/users", label: "Users", roles: ["admin"], group: "Admin" },
  { to: "/admin/widgets", label: "Widgets & Columns", roles: ["admin"], group: "Admin" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><img src={logo} alt="DSR" className="logo" /> <b>CONTROL TOWER</b></div>
        <div className="title">CONTAINER LOADING MONITORING<small>PV MODULES</small></div>
        <div className="who">
          <span>{user?.name}</span> <em className="role">{user?.role}</em>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </header>
      <aside className="sidebar">
        {NAV.filter((n) => !n.roles || n.roles.includes(user!.role)).map((n, i, arr) => (
          <div key={n.to}>
            {n.group && arr[i - 1]?.group !== n.group && <div className="nav-group">{n.group}</div>}
            <NavLink to={n.to} end={n.end} className={({ isActive }) => "nav" + (isActive ? " active" : "")}>{n.label}</NavLink>
          </div>
        ))}
      </aside>
      <main className="content"><Outlet /></main>
    </div>
  );
}
