import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, WidgetSetting } from "../api";
import { MODULES } from "../modules";


export default function AdminWidgets() {
  const qc = useQueryClient();
  const [MODULE, setModule] = useState(MODULES[0].key);
  const q = useQuery({ queryKey: ["widget-admin", MODULE], queryFn: () => api<WidgetSetting[]>(`/admin/widgets/${MODULE}`) });
  const [err, setErr] = useState<string | null>(null);

  const save = async (key: string, json: object) => {
    try {
      setErr(null);
      await api(`/admin/widgets/${MODULE}/${key}`, { method: "PUT", json });
      await qc.invalidateQueries({ queryKey: ["widget-admin", MODULE] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["ps-dashboard"] });
      qc.invalidateQueries({ queryKey: ["psi-dashboard"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div>
      <h2>Widgets &amp; Columns</h2>
      <label className="inline-select">Dashboard
        <select value={MODULE} onChange={(e) => setModule(e.target.value)}>{MODULES.map((m) => <option key={m.key} value={m.key}>{m.title}</option>)}</select>
      </label>
      <p className="muted">Hidden widgets and columns are removed from the dashboard for every user (the server does not send them).</p>
      {err && <div className="alert error">{err}</div>}
      <div className="widget-list">
        {(q.data ?? []).map((w) => (
          <div className="card" key={w.key}>
            <label className="check big">
              <input type="checkbox" checked={w.visible} onChange={(e) => save(w.key, { visible: e.target.checked })} />
              <b>{w.title}</b>
            </label>
            {Object.keys(w.columns).length > 0 && (
              <div className="cols">
                {Object.entries(w.columns).map(([k, on]) => (
                  <label className="check" key={k}>
                    <input type="checkbox" checked={on} disabled={!w.visible} onChange={(e) => save(w.key, { columns: { [k]: e.target.checked } })} />
                    {w.columnLabels[k]}
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
