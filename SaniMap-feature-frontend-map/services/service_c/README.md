# Maintenance Work Order Service

Service C manages operational maintenance jobs created from visitor reports.
Reporting (Service B) remains the source of visitor feedback; this service
separately owns job assignment, priority, status, and an append-only event
history. Completing a work order does not change the report's status.

## Run locally

From the project root:

```powershell
python -m pip install -r .\services\service_c\requirements.txt
python .\services\service_c\App_ServiceC.py
```

The service listens on `127.0.0.1:5003`. It creates
`services/service_c/work_orders.db` on first run. Configure
`SANIMAP_WORK_ORDERS_DB` to change the database path and
`SANIMAP_REPORTING_URL` to point to Service B. A report must exist in the
Reporting Service before a work order can be created.

## API

All work-order routes should be called through the API Gateway; the Gateway
requires an `admin` or `park_manager` token for each of them.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/work-orders` | Create one job from an existing `reportId` |
| `GET` | `/work-orders` | List jobs; optional `status`, `reportId`, `restroomId`, `limit`, and `offset` filters |
| `GET` | `/work-orders/{workOrderId}` | Get a job |
| `PUT` | `/work-orders/{workOrderId}` | Update status, assignment, priority, title, or description |
| `GET` | `/work-orders/{workOrderId}/history` | Read the job's creation and change events |

Statuses are `OPEN`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`. Priorities
are `LOW`, `MEDIUM`, `HIGH`, and `URGENT`. Only one work order may be created
for a report. A job snapshots the report's restroom identity and description;
later report edits do not rewrite the maintenance record.

Example request through a local Gateway:

```powershell
curl.exe -i -X POST http://127.0.0.1:5000/work-orders `
  -H "Authorization: Bearer <staff-token>" `
  -H "Content-Type: application/json" `
  -d "{\"reportId\":501,\"priority\":\"HIGH\",\"assignedTo\":\"Facilities team\"}"
```

The Reporting Service returns `404` for an unknown report, `503` if Reporting
cannot be reached, and `502` for an invalid upstream response. Duplicate jobs
return `409`. Invalid JSON or fields return a structured `400`; unsupported
media types return `415`.

## Render

Use this directory as the Render service's Root Directory, install with
`pip install -r requirements.txt`, and start with
`gunicorn --bind 0.0.0.0:$PORT App_ServiceC:app`. Set
`SANIMAP_REPORTING_URL` to the Reporting service's internal URL. Attach a
persistent disk and set `SANIMAP_WORK_ORDERS_DB` to a database file within its
mount path. Keep the service private and run one instance while using SQLite.
