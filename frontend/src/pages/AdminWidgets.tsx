import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, WidgetSetting } from "../api";

const MODULE = "container_loading";

export default function AdminWidgets() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["widget-admin"], queryFn: () => api<WidgetSetting[]>(`/admin/widgets/${MODULE}`) });
  const [err, setErr] = useState<string | null>(null);

  const save = async (key: string, json: object) => {
    try {
      setErr(null);
      await api(`/admin/widgets/${MODULE}/${key}`, { method: "PUT", json });
      await qc.invalidateQueries({ queryKey: ["widget-admin"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <div>
      <h2>Widgets &amp; Columns — Container Loading Monitoring</h2>
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
