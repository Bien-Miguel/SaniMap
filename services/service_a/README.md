# Comfort Room Registry Service

Registry Service for SaniMap. It stores restroom records in SQLite and
provides JSON/XML endpoints on port `5001`.

## Run

From the repository root:

```powershell
py -m pip install -r .\services\requirements
py .\services\service_a\App_ServiceA.py
```

The default database is `services/service_a/registry.db`. Set
`SANIMAP_REGISTRY_DB` to use a different database path. The database and seed
records are initialized automatically; seed data is added only when the table
is empty.

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

## Example

```powershell
curl.exe -i http://127.0.0.1:5001/restrooms/1
curl.exe -i -X PUT http://127.0.0.1:5001/restrooms/1/status `
  -H "Content-Type: application/json" `
  -d "{\"status\":\"closed\"}"
```
