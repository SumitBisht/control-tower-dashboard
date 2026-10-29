import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useRef, useState } from "react";
import { api, Upload } from "../api";
import { useAuth } from "../auth";

const MAX_MB = 25;

function LogView({ u }: { u: Upload }) {
  return (
    <div className="log">
      <div className={`log-head ${u.status.toLowerCase()}`}>
        <b>{u.fileName}</b> — {u.status.replace(/_/g, " ")}
        {u.summary && <span> · {u.summary.containers} containers, {u.summary.modules?.toLocaleString()} modules</span>}
      </div>
      {(u.logs ?? []).map((l, i) => (
        <div key={i} className={`log-line ${l.level.toLowerCase()}`}>
          <span className="ts">{new Date(l.ts).toLocaleTimeString()}</span>
          <span className="lvl">{l.level}</span>
          <span>{l.message}</span>
        </div>
      ))}
    </div>
  );
}

export default function Uploads() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [spv, setSpv] = useState("");
  const [project, setProject] = useState("");
  const [replace, setReplace] = useState(false);
  const [result, setResult] = useState<Upload | null>(null);
  const [clientErr, setClientErr] = useState<string | null>(null);
  const history = useQuery({ queryKey: ["uploads"], queryFn: () => api<Upload[]>("/uploads") });

  const pick = (f: File | null) => {
    setResult(null);
    setClientErr(null);
    if (f && !f.name.toLowerCase().endsWith(".docx")) { setClientErr("Only .docx files are accepted."); return; }
    if (f && f.size > MAX_MB * 1024 * 1024) { setClientErr(`File is larger than ${MAX_MB} MB.`); return; }
    setFile(f);
  };

  const up = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("spv_name", spv);
      form.append("project_name", project);
      form.append("replace", String(replace));
      return api<Upload>("/uploads", { method: "POST", form });
    },
    onSuccess: (r) => {
      setResult(r);
      if (r.status !== "FAILED") { setFile(null); if (fileRef.current) fileRef.current.value = ""; }
      qc.invalidateQueries({ queryKey: ["uploads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["filters"] });
    },
    onError: (e) => setClientErr((e as Error).message),
  });

  const view = async (id: string) => setResult(await api<Upload>(`/uploads/${id}`));
  const del = async (id: string) => {
    if (!confirm("Delete this upload and all data it created?")) return;
    await api(`/uploads/${id}`, { method: "DELETE" });
    setResult(null);
    qc.invalidateQueries();
  };

  return (
    <div>
      <h2>Upload report</h2>
      <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); if (file) up.mutate(); }}>
        <div className="drop"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0] ?? null); }}
          onClick={() => fileRef.current?.click()}>
          {file ? <><b>{file.name}</b> ({(file.size / 1024).toFixed(0)} KB)</> : "Drop the DSR Container Loading Monitoring report (.docx) here, or click to browse"}
          <input ref={fileRef} type="file" accept=".docx" hidden onChange={(e) => pick(e.target.files?.[0] ?? null)} />
        </div>
        <div className="form-row">
          <label>SPV name <small>(optional — defaults to the configured client name)</small>
            <input value={spv} onChange={(e) => setSpv(e.target.value)} /></label>
          <label>Project name <small>(optional — defaults to the report location)</small>
            <input value={project} onChange={(e) => setProject(e.target.value)} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace existing report with the same Report No.</label>
        {clientErr && <div className="alert error">{clientErr}</div>}
        <button className="primary" disabled={!file || up.isPending}>{up.isPending ? "Processing…" : "Upload & process"}</button>
      </form>

      {result && <LogView u={result} />}

      <h2>Upload history</h2>
      <table className="grid">
        <thead><tr><th>When</th><th>File</th><th>By</th><th>Status</th><th>Errors</th><th>Warnings</th><th /></tr></thead>
        <tbody>
          {(history.data ?? []).map((u) => (
            <tr key={u.id}>
              <td>{new Date(u.uploadedAt).toLocaleString()}</td><td>{u.fileName}</td><td>{u.uploadedBy}</td>
              <td><span className={`pill st-${u.status.toLowerCase()}`}>{u.status.replace(/_/g, " ")}</span></td>
              <td>{u.counts.ERROR}</td><td>{u.counts.WARNING}</td>
              <td className="actions"><button className="link" onClick={() => view(u.id)}>View log</button>
                {user?.role === "admin" && <button className="link danger" onClick={() => del(u.id)}>Delete</button>}</td>
            </tr>
          ))}
          {history.data?.length === 0 && <tr><td colSpan={7} className="empty">No uploads yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
