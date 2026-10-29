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


def table_payload(module: ReportModule, widget_key: str, rows: list[dict], visible_cols: set[str], keep: tuple[str, ...] = ()) -> dict:
    """Table widget response containing only the columns the admin left visible (hidden columns never leave the server)."""
    wdef = next(x for x in module.widgets if x.key == widget_key)
    columns = [{"key": c.key, "label": c.label} for c in wdef.columns if c.key in visible_cols]
    allowed = {c["key"] for c in columns} | set(keep)
    return {"columns": columns, "rows": [{k: v for k, v in row.items() if k in allowed} for row in rows]}
