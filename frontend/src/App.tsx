import { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Role } from "./api";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import AdminUsers from "./pages/AdminUsers";
import AdminWidgets from "./pages/AdminWidgets";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Uploads from "./pages/Uploads";

function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-msg">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Guard><Layout /></Guard>}>
        <Route index element={<Dashboard />} />
        <Route path="uploads" element={<Guard roles={["uploader", "admin"]}><Uploads /></Guard>} />
        <Route path="admin/users" element={<Guard roles={["admin"]}><AdminUsers /></Guard>} />
        <Route path="admin/widgets" element={<Guard roles={["admin"]}><AdminWidgets /></Guard>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
