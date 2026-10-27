# Comfort Room Registry Service

Registry Service for SaniMap. It stores restroom records in SQLite and
provides JSON/XML endpoints on port `5001`.

## Run

From the repository root:

```powershell
python -m pip install -r .\services\service_a\requirements.txt
python .\services\service_a\App_ServiceA.py
```

The default database is `services/service_a/registry.db`. Set
`SANIMAP_REGISTRY_DB` to use a different database path. The database and seed
records are initialized automatically. The five canonical Luneta facilities
are inserted whenever missing, including when the database already contains
other records. Existing seeded facility details are aligned with the canonical
coordinates and amenities on startup, while their current status is preserved.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health |
| `GET` | `/restrooms` | List restroom records |
| `GET` | `/restrooms/{restroomId}` | Get one record |
| `POST` | `/restrooms` | Create a record |
| `PUT` | `/restrooms/{restroomId}/status` | Update a record's status |

Use `Accept: application/xml` for XML responses. Creation and status updates
accept `Content-Type: application/json` or `application/xml`.

Restroom records use integer `restroomId` values and these fields:
`name`, `latitude`, `longitude`, `operatingHours`, `pwdAccessible`,
`genderType`, `amenities`, and `status`. Status must be `open`, `closed`, or
`under_maintenance`.

Errors have a JSON or XML body with an `error` code and `message`. Common
status codes are `400` for malformed or invalid input, `404` for a missing
record, `409` for a duplicate ID, and `415` for an unsupported request media
type.

Railway deployment uses this directory as the service root and starts the app
with `gunicorn --bind 0.0.0.0:$PORT App_ServiceA:app`. Attach a persistent
volume and set `SANIMAP_REGISTRY_DB` to a path inside its mount.

## Render deployment and persistence

The service exposes `GET /health` for a simple health check and
`GET /restrooms` for both a health/data check and a request that wakes a
spun-down service. The Gateway also exposes `GET /health`, which checks only
the Gateway; `GET /restrooms` through the Gateway exercises the Registry
upstream.

This service uses SQLite. Its default database path is under this service's
source directory, which is ephemeral on Render. A free Render web service
spins down after inactivity and loses local filesystem changes when it spins
down or restarts; free services cannot use persistent disks. For durable SQLite
storage, use a paid web service, attach a disk mounted at `/var/data`, and set
`SANIMAP_REGISTRY_DB=/var/data/registry.db`. Without durable storage, records
created at runtime (for example, through the admin dashboard) can disappear
after a spin-down, restart, or redeploy. The canonical five seed facilities
will be inserted again automatically when the Registry starts.

## Example

```powershell
curl.exe -i http://127.0.0.1:5001/restrooms/1
curl.exe -i -X PUT http://127.0.0.1:5001/restrooms/1/status `
  -H "Content-Type: application/json" `
  -d "{\"status\":\"closed\"}"
```
