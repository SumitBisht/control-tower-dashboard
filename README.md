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

## Upload behaviour (graceful termination)
Parse is pure (writes nothing). Any **ERROR** (not a .docx, corrupt/oversized zip, placeholder `xxxxx` Report No./Date,
missing containers table, invalid quantity/date, duplicate report, ...) aborts the whole upload: nothing is saved, status
`FAILED`, and *all* problems are listed in the log. **WARNING**s (seal mismatch, missing per-container section, summary-table
mismatch, unknown PSI lot...) are saved and shown. Save failures are rolled back. Parsing has a timeout and the file a size limit.
The unfilled template itself is rejected by design.

Data not in the Word file: **SPV** and **Project** names are optional upload-form fields
(default: CLIENT_NAME setting / report location). PSI lot is taken from the document's summary table by (loading date, product type).

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
Set `CLIENT_NAME` (env or `backend/.env`; `client_name` in Terraform). Precedence for a report's SPV:
upload-form value → `CLIENT_NAME` → client name in the Word document.
