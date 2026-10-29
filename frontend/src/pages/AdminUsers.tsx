import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api, Role, User } from "../api";
import { useAuth } from "../auth";

const ROLES: { value: Role; label: string }[] = [
  { value: "viewer", label: "Viewer" },
  { value: "uploader", label: "Viewer + Uploader" },
  { value: "admin", label: "Admin" },
];

export default function AdminUsers() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/admin/users") });
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "viewer" as Role });

  const run = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { setErr(null); qc.invalidateQueries({ queryKey: ["users"] }); },
    onError: (e) => setErr((e as Error).message),
  });
  const patch = (id: string, json: object) => run.mutate(() => api(`/admin/users/${id}`, { method: "PATCH", json }));
  const create = (e: FormEvent) => {
    e.preventDefault();
    run.mutate(async () => { await api("/admin/users", { method: "POST", json: form }); setForm({ name: "", email: "", password: "", role: "viewer" }); });
  };
  const pending = (users.data ?? []).filter((u) => u.status === "pending");

  return (
    <div>
      <h2>Users</h2>
      {err && <div className="alert error">{err}</div>}
      {pending.length > 0 && <div className="alert info">{pending.length} account(s) awaiting approval.</div>}
      <table className="grid">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
        <tbody>
          {(users.data ?? []).map((u) => (
            <tr key={u.id}>
              <td>{u.name}</td><td>{u.email}</td>
              <td><select value={u.role} disabled={u.id === me?.id} onChange={(e) => patch(u.id, { role: e.target.value })}>
                {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select></td>
              <td><span className={`pill st-${u.status}`}>{u.status}</span></td>
              <td className="actions">
                {u.status === "pending" && <button className="primary sm" onClick={() => patch(u.id, { status: "active" })}>Approve</button>}
                {u.status === "active" && u.id !== me?.id && <button className="link" onClick={() => patch(u.id, { status: "disabled" })}>Disable</button>}
                {u.status === "disabled" && <button className="link" onClick={() => patch(u.id, { status: "active" })}>Enable</button>}
                {u.id !== me?.id && <button className="link danger" onClick={() => confirm(`Delete ${u.email}?`) && run.mutate(() => api(`/admin/users/${u.id}`, { method: "DELETE" }))}>Delete</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Add user</h2>
      <form className="card form-row" onSubmit={create}>
        <input placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input type="email" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        <input type="password" placeholder="Temporary password (min 8)" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</select>
        <button className="primary">Create (active)</button>
      </form>
    </div>
  );
}
