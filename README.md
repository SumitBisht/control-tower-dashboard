# DSR Control Tower

FastAPI + MongoDB backend, React (Vite, TypeScript) frontend. First module: **Container Loading Monitoring**,
fed by uploading the DSR Word report.

## Run locally
```bash
docker compose up --build        # UI http://localhost:8080, API http://localhost:8000/docs
```
or without Docker (needs a MongoDB on localhost:27017):
```bash
cd backend && python -m venv .venv && . .venv/Scripts/activate && pip install -r requirements.txt
cp .env.example .env && uvicorn app.main:app --reload
cd frontend && npm install && npm run dev      # http://localhost:5173
```
First start seeds an admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. **Change it and `JWT_SECRET` before deploying.**

## Roles
| role | can |
|---|---|
| `viewer` | see the dashboard |
| `uploader` | viewer + upload Word reports, see own upload logs |
| `admin` | everything + approve/create/disable/delete users, show/hide widgets and table columns, delete uploads |

Self-registered users are `pending` until an admin approves them.

## Upload behaviour
Uploads run **in the background**: `POST /api/uploads` returns `202` immediately and the UI polls the upload until it finishes
(real reports with photos are ~100 MB; limit `MAX_UPLOAD_MB`, default 250). The original `.docx` is kept in storage and can be
re-downloaded from the Reports tab.

Graceful termination: parse is pure (writes nothing). Any **ERROR** (not a .docx, corrupt/oversized zip, placeholder `xxxxx` Report
No./Date, missing containers table, invalid quantity/date, duplicate report, parse timeout, ...) aborts the whole upload: nothing is
saved, status `FAILED`, and *all* problems are listed in the log. **WARNING**s (seal mismatch, missing per-container section,
summary-table mismatch, unknown PSI lot...) are saved and shown. Save failures are rolled back (a failed *replace* restores the old
report). Uploads orphaned by a server restart are marked `FAILED` on the next start.

Supported layout (both DSR template versions): header tables (Report No/Date/Manufacturer/Location/Workshop, and either
`Client / Project Name / SPV Name` or the older `Client Details` block), summary table, containers table (Seal column optional),
per-container `Container Number N` sections (Shipment details, Summary of Inspection, photo tables - every photo is stored).
SPV / Project come from the document; the upload form can override them, and `CLIENT_NAME` sets the client.
PSI lot comes from the summary table by (loading date, product type); a date spanning lots (e.g. `1, 2`) assigns both lots.
The unfilled template itself is rejected by design.

## Reports tab
Search containers/reports by loading date range, product type (model), manufacturer, SPV, project, PSI lot and free text
(report no, container no, seal no...). From the results: download the **original Word report**, or **export Excel/CSV**
(one row per matching container incl. inspection + checklist results; up to 50,000 rows).

## Extending (template use)
Add `backend/app/modules/<name>/` with a `ReportModule` subclass (`parse`, `persist`, widgets catalogue, router),
register it in `modules/registry.py`. Uploads, widget/column admin and `/api/modules` work automatically.
Frontend: add a nav entry in `components/Layout.tsx` and a page. `src/api.ts` has no DOM dependencies for reuse in React Native.

## Tests
`cd backend && pytest` — parser tests always run; `tests/test_api.py` runs when MongoDB is reachable.
Regenerate the filled sample report: `python tests/make_sample.py`.

## AWS
Terraform (MongoDB Atlas + ECS Fargate + S3/CloudFront) is in `infra/terraform`; see **[docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md)**
for architecture, first-deploy steps, cost and hardening notes.

## Client / SPV name
Set `CLIENT_NAME` (env or `backend/.env`; `client_name` in Terraform) to fix the client name shown/stored on reports
(otherwise the `Client` row of the document is used). SPV precedence: upload form → SPV in the document → `CLIENT_NAME` → client in the document.
