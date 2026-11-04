# MongoDB data model

Diagram: [dsr_data_model.drawio](dsr_data_model.drawio) (open with diagrams.net). Pages: relational ER (reference), MongoDB model
(container loading), **MongoDB - Production Supervision**, **MongoDB - Pre-Shipment Inspection**.

## Container Loading Monitoring
`projects`, `product_types`, `reports`, `containers` (one doc per container with shipment + inspection + checklist embedded).
Photos and the original `.docx` are kept in storage (`photos/<reportId>/...`, `originals/<uploadId>/...`).

## Production Supervision
| Collection | One document per | Purpose |
|---|---|---|
| `ps_reports` | uploaded report | header, signatories, roll-up `summary` (days, actual/planned output, rejected/suspected, open NCs, BOM/IPQC counts) |
| `ps_production` | report x date x power bin | planned / actual / deviation / day shift / night shift, each `{qty, mwp}` |
| `ps_qualification` | report x date (+1 `cumulative` row) | qualified modules per power bin, rejected, EL rework rejected, suspected |
| `ps_nc` | report x non-conformity | NC with `status` OPEN/CLOSED and a `key` that identifies the same NC across reports |
| `ps_details` | report | BOM + storage conditions, IPQC, flasher, soldering peel, gel, dimension, RFID, lab tests, calibration, `quality` roll-up |

Rules worth knowing:
- **Reports are cumulative** (each repeats earlier days). Rows are stored per report; the dashboard keeps the latest report's version
  of each `(projectName, date, powerBin)` / NC, so re-issued numbers and NC status changes (Open -> Closed) win automatically.
  Rolling back or deleting an upload therefore never leaves holes in older reports.
- Every row carries `reportId`, `reportNo`, `reportDate`, `spvName`, `projectName`, `manufacturer`, `uploadId` (cheap filtering, simple cascade delete).
- **No media is stored**: images/videos in the Word file are never read, and the original `.docx` is not kept (it contains the media).
- Shared collections: `users`, `uploads` (status + log per upload), `widget_settings` (per-module widget/column visibility).

## Pre-Shipment Inspection
One report per production lot. Reports are independent (not cumulative); if a lot is re-issued under a new report number, the dashboard
shows the latest report for each `(projectName, lotNo)`.

| Collection | One document per | Purpose |
|---|---|---|
| `psi_reports` | report / lot | header, `lot{lotNo,factory,sizePcs,sizeMwp}`, `wattClasses[]`, `conclusion`, signatories, roll-up `summary` |
| `psi_results` | inspection/test row | standard, AQL, sampling, observation, `decision` PASS/FAIL, remarks |
| `psi_nc` | non-conformity | test, category, description, risk, count |
| `psi_details` | report | test conditions + equipment calibration dates, sun-simulator checks, maximum-power rows (per module) + min/max/avg, per-test NC summaries and module lists, insulation, wet leakage, bi-faciality, mechanical loads, robustness, low irradiance |

Same rules as above: every row carries `reportId/reportNo/reportDate/spvName/projectName/manufacturer/lotNo/uploadId`; no media and no original `.docx` are stored.

## BOM Assessment (`bom_*`)
One report per verification visit. Every report is kept (batches change between visits); the dashboard lists all reports matching the filters.

| Collection | One document per | Purpose |
|---|---|---|
| `bom_reports` | report | header (client, SPV, project, manufacturer, location, workshop), roll-up `summary` (materials, passed, underReview, deviations, storage counts, avg temperature/humidity) |
| `bom_materials` | material | `bomMake/actualMake`, `bomOrigin/actualOrigin`, `batchNo`, `result` PASS/FAIL/UNDER REVIEW, `remarks`, `deviation` flag |
| `bom_storage` | stored material | `temperatureC`, `humidityPct`, `expiry`, `observation`, `result`, `remarks` |

## Pre-Production Audit (`ppa_*`)
One report per audit. Every report is kept.

| Collection | One document per | Purpose |
|---|---|---|
| `ppa_reports` | report | header, `audit{factory,site,address,type,sequence,benchmark,scope,auditDate}`, `conclusion`, `signatories`, `extra.sections` (checks/closed per section), roll-up `summary` |
| `ppa_checks` | readiness check | `section`, `item`, `requirement`, `evidence`, `status` CLOSED/OPEN, `statusNote` (e.g. "First 50MW") |
| `ppa_nc` | non-conformity | `line`, `date`, `description`, `severity` Major/Minor, `process`, `status`, `statusNote` |

Same rules as above: every row carries `reportId/reportNo/reportDate/spvName/projectName/manufacturer/uploadId`; no media and no original `.docx` are stored.
