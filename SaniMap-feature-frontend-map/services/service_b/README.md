# Reporting and Feedback Service

Reporting Service for SaniMap. It validates reports against the Registry
Service, stores them in SQLite, and serves endpoints on port `5002`.

## Run

From the repository root:

```powershell
python -m pip install -r .\services\service_b\requirements.txt
python .\services\service_b\App_ServiceB.py
```

Start the Registry Service on port `5001` before creating reports. The default
database is `services/service_b/reporting.db`. Set `SANIMAP_REPORTING_DB` to
use a different database path. Set `SANIMAP_REGISTRY_URL` if the Registry is
not available at `http://127.0.0.1:5001`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health |
| `POST` | `/feedback` | Validate and create a report |
| `GET` | `/feedback/{restroomId}` | List reports for a restroom |
| `GET` | `/feedback/reports/{reportId}` | Get a report and its current status |

Use `Accept: application/xml` to request XML responses. Report creation accepts
JSON or XML with `Content-Type: application/json` or `application/xml`.

Example JSON request:

```json
{
  "restroomId": 1,
  "reportType": "UNSANITARY_FACILITY",
  "description": "Bidet is broken and the floor is wet."
}
```

`restroomId` must be a positive integer and must exist in the Registry.
`reportType` must be one of `UNSANITARY_FACILITY`, `CLEANLINESS`,
`DAMAGED_FIXTURE`, `OUT_OF_WATER`, `CLOSED`, or `OTHER`. Reports are assigned
database-generated `reportId` values, start with status `PENDING`, and include
a UTC ISO 8601 `createdAt` timestamp.

Railway deployment uses this directory as the service root and starts the app
with `gunicorn --bind 0.0.0.0:$PORT App_ServiceB:app`. Attach a separate
persistent volume and set `SANIMAP_REPORTING_DB` to a path inside its mount.

The Registry lookup returns `404` if the restroom does not exist and `503` if
the Registry is unavailable. Malformed JSON/XML returns `400`; unsupported
request media types return `415`.

## Example

```powershell
curl.exe -i -X POST http://127.0.0.1:5002/feedback `
  -H "Content-Type: application/json" `
  -H "Accept: application/json" `
  -d "{\"restroomId\":1,\"reportType\":\"UNSANITARY_FACILITY\",\"description\":\"Broken bidet\"}"
```
