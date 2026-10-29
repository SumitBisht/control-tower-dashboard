import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import logo from "../assets/logo.jpeg";

export default function Login() {
  const { user, login } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ name: "", email: "", password: "" });
  const [msg, setMsg] = useState<{ kind: "error" | "ok"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      if (mode === "login") await login(f.email, f.password);
      else {
        const r = await api<{ message: string }>("/auth/register", { method: "POST", json: f });
        setMsg({ kind: "ok", text: r.message });
        setMode("login");
      }
    } catch (err) {
      setMsg({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="card login" onSubmit={submit}>
        <h1><img src={logo} alt="DSR" className="logo" /> <b>CONTROL TOWER</b></h1>
        <h2>{mode === "login" ? "Sign in" : "Request access"}</h2>
        {msg && <div className={`alert ${msg.kind}`}>{msg.text}</div>}
        {mode === "register" && <input placeholder="Full name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />}
        <input type="email" placeholder="Email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoFocus />
        <input type="password" placeholder="Password" minLength={mode === "register" ? 8 : undefined} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <button className="primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Register"}</button>
        <button type="button" className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setMsg(null); }}>
          {mode === "login" ? "No account? Request access" : "Back to sign in"}
        </button>
      </form>
    </div>
  );
}
