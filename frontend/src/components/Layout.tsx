import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import logo from "../assets/logo.jpeg";
import { useAppConfig } from "../useAppConfig";
import { chevrons, headingFor, NAV } from "./nav";

const KEY = "ct_nav_collapsed";

function useCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch { /* storage unavailable: the choice just won't persist */ }
  }, [collapsed]);
  return [collapsed, () => setCollapsed((c) => !c)];
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { clientName } = useAppConfig();
  const { pathname } = useLocation();
  const [collapsed, toggle] = useCollapsed();
  const items = NAV.filter((n) => !n.roles || n.roles.includes(user!.role));

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <header className="topbar">
        <div className="brand"><img src={logo} alt="DSR" className="logo" /> <b>CONTROL TOWER</b></div>
        <div className="title">{headingFor(pathname)}<small>PV MODULES</small></div>
        {clientName && <div className="client">{clientName}</div>}

        <div className="who">
          <span>{user?.name}</span> <em className="role">{user?.role}</em>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </header>
      <aside className="sidebar" aria-label="Main menu">
        <button type="button" className="nav-toggle" onClick={toggle} aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand menu" : "Collapse menu"} title={collapsed ? "Expand menu" : "Collapse menu"}>
          {chevrons(!collapsed)}
        </button>
        {items.map((n, i) => (
          <div key={n.to}>
            {n.group && items[i - 1]?.group !== n.group && <div className="nav-group"><span className="label">{n.group}</span></div>}
            <NavLink to={n.to} className={({ isActive }) => "nav" + (isActive ? " active" : "") + (n.soon ? " soon" : "")}
              title={collapsed ? n.label : undefined} aria-label={n.label}>
              <span className="icon">{n.icon}</span>
              <span className="label">{n.label}</span>
              {n.soon && <em className="tag">Soon</em>}
            </NavLink>
          </div>
        ))}
      </aside>
      <main className="content"><Outlet /></main>
    </div>
  );
}
