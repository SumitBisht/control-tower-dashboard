"""Per-module widget visibility / column visibility, merged over defaults from the module's catalogue."""
from .modules.base import ReportModule


async def get_widget_settings(db, module: ReportModule) -> dict[str, dict]:
    stored = {d["widgetKey"]: d async for d in db.widget_settings.find({"module": module.key})}
    out = {}
    for w in module.widgets:
        s = stored.get(w.key, {})
        cols = {c.key: s.get("columns", {}).get(c.key, True) for c in w.columns}
        out[w.key] = {"key": w.key, "title": w.title, "kind": w.kind, "visible": s.get("visible", True),
                      "columns": cols, "columnLabels": {c.key: c.label for c in w.columns}}
    return out
