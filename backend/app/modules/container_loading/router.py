from fastapi import APIRouter, Depends, Query

from ...core.db import get_db
from ...deps import get_current_user
from ...widgets import get_widget_settings, table_payload as _table
from .module import CHECKLIST_LABELS
from .reports import add_report_routes


def _filters(spv, project, manufacturer, psi_lot) -> dict:
    m = {}
    for field, val in (("spvName", spv), ("projectName", project), ("manufacturer", manufacturer), ("psiLots", psi_lot)):
        if val and val != "All":
            m[field] = val
    return m


def _iso(d) -> str:
    return d.strftime("%Y-%m-%d")


def build_router(module) -> APIRouter:
    r = APIRouter(prefix=f"/{module.key}", tags=[module.key])

    @r.get("/filters")
    async def filters(user=Depends(get_current_user)):
        db = get_db()
        out = {}
        for key, field in (("spv", "spvName"), ("project", "projectName"), ("manufacturer", "manufacturer"), ("psi_lot", "psiLots")):
            out[key] = sorted(await db.containers.distinct(field), key=lambda x: (len(str(x)), str(x)))
        out["model"] = sorted(await db.containers.distinct("modelCode"))
        return out

    @r.get("/dashboard")
    async def dashboard(spv: str | None = None, project: str | None = None, manufacturer: str | None = None,
                        psi_lot: str | None = Query(None), user=Depends(get_current_user)):
        db = get_db()
        settings = await get_widget_settings(db, module)
        visible = {k for k, s in settings.items() if s["visible"]}
        cols = {k: {c for c, on in s["columns"].items() if on} for k, s in settings.items()}

        pipeline = [{"$match": _filters(spv, project, manufacturer, psi_lot)}, {"$facet": {
            "kpi": [{"$group": {"_id": None, "containers": {"$sum": 1}, "modules": {"$sum": "$moduleQty"},
                                "capacityKwp": {"$sum": "$capacityKwp"},
                                "passed": {"$sum": {"$cond": [{"$eq": ["$inspection.result", "PASS"]}, 1, 0]}},
                                "inspected": {"$sum": {"$cond": [{"$in": ["$inspection.result", ["PASS", "FAIL"]]}, 1, 0]}}}}],
            "trend": [{"$group": {"_id": {"d": "$loadingDate", "w": "$nominalPowerWp"}, "modules": {"$sum": "$moduleQty"}}}],
            "product": [{"$group": {"_id": "$modelCode", "containers": {"$sum": 1}, "modules": {"$sum": "$moduleQty"},
                                    "capacityKwp": {"$sum": "$capacityKwp"}}}, {"$sort": {"_id": 1}}],
            "recent": [{"$group": {"_id": {"lot": "$psiLotNo", "d": "$loadingDate", "m": "$modelCode", "w": "$nominalPowerWp"},
                                   "n": {"$sum": 1}, "capacityKwp": {"$sum": "$capacityKwp"}}}],
            "checklist": [{"$project": {"c": {"$objectToArray": {"$ifNull": ["$inspection.checklist", {}]}}}},
                          {"$unwind": "$c"}, {"$group": {"_id": {"k": "$c.k", "v": "$c.v"}, "n": {"$sum": 1}}}],
        }}]
        res = (await (await db.containers.aggregate(pipeline)).to_list(1))[0]
        kpi = res["kpi"][0] if res["kpi"] else {"containers": 0, "modules": 0, "capacityKwp": 0, "passed": 0, "inspected": 0}

        out: dict = {"widgets": {}}
        w = out["widgets"]
        if "kpi_containers" in visible:
            w["kpi_containers"] = {"value": kpi["containers"]}
        if "kpi_modules" in visible:
            w["kpi_modules"] = {"value": kpi["modules"]}
        if "kpi_capacity" in visible:
            w["kpi_capacity"] = {"value": round(kpi["capacityKwp"] / 1000, 3), "unit": "MWp"}
        if "kpi_result" in visible:
            pct = round(100 * kpi["passed"] / kpi["inspected"], 1) if kpi["inspected"] else None
            w["kpi_result"] = {"value": pct, "passed": kpi["passed"], "inspected": kpi["inspected"], "unit": "% success"}
        if "loading_trend" in visible:
            wps = sorted({t["_id"]["w"] for t in res["trend"]})
            by_date: dict = {}
            for t in res["trend"]:
                by_date.setdefault(_iso(t["_id"]["d"]), {})[f"{t['_id']['w']:g} Wp"] = t["modules"]
            series = [f"{x:g} Wp" for x in wps]
            running = {s: 0 for s in series}
            data = []
            for d, v in sorted(by_date.items()):  # cumulative modules loaded up to each date
                for s in series:
                    running[s] += v.get(s, 0)
                data.append({"date": d, **running})
            w["loading_trend"] = {"series": series, "cumulative": True, "data": data}
        if "product_summary" in visible:
            c = cols["product_summary"]
            rows = [{"product_type": p["_id"], "containers": p["containers"], "modules": p["modules"],
                     "capacity_mwp": round(p["capacityKwp"] / 1000, 3)} for p in res["product"]]
            w["product_summary"] = _table(module, "product_summary", rows, c)
        if "recent_containers" in visible:
            groups: dict = {}
            for g in res["recent"]:
                k = (g["_id"]["lot"], g["_id"]["d"], g["_id"]["m"])
                e = groups.setdefault(k, {"psi_lot": k[0], "loading_date": _iso(k[1]), "product_type": k[2],
                                          "containers_total": 0, "containers_by_wp": {}, "capacity_mwp": 0.0})
                e["containers_total"] += g["n"]
                e["containers_by_wp"][f"{g['_id']['w']:g}"] = e["containers_by_wp"].get(f"{g['_id']['w']:g}", 0) + g["n"]
                e["capacity_mwp"] = round(e["capacity_mwp"] + g["capacityKwp"] / 1000, 3)
            rows = sorted(groups.values(), key=lambda x: x["loading_date"], reverse=True)[:10]
            wps = sorted({k for r_ in rows for k in r_["containers_by_wp"]}, key=float)
            t = _table(module, "recent_containers", rows, cols["recent_containers"])
            t["wp_classes"] = wps
            w["recent_containers"] = t
        if "checklist_summary" in visible:
            agg: dict = {}
            for g in res["checklist"]:
                agg.setdefault(g["_id"]["k"], {})[g["_id"]["v"]] = g["n"]
            rows = []
            for key, label in CHECKLIST_LABELS.items():
                counts = agg.get(key, {})
                status = "NOK" if counts.get("NOK") else "OK" if counts.get("OK") else "NA" if counts else "-"
                rows.append({"item": label, "status": status, "counts": counts})
            w["checklist_summary"] = _table(module, "checklist_summary", rows, cols["checklist_summary"], keep=("counts",))
        return out

    add_report_routes(r)
    return r


