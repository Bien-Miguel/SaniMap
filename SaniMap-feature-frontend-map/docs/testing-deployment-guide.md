# SaniMap setup, testing, monitoring, and deployment guide

This guide matches the current repository. Do not treat mock data or a green
Gateway-only health check as proof that both backend services are healthy.

## 1. What is in the repository today

| Area | Current state |
| --- | --- |
| Registry | SQLite-backed REST service, seeded with two restroom records. |
| Reporting | SQLite-backed reporting service; creates reports and validates restroom IDs against the registry. |
| Gateway | Routes registry, reporting, geocoding, and directions requests. Staff-only routes use JWT roles. |
| Frontend | React/Vite app; mock mode is the default. Use `VITE_USE_MOCK_API=false` to use the gateway. |
| Health monitoring | `GET /health` checks only the gateway process. Staff-only `GET /health/all` now checks both backend services and returns HTTP 503 if either is down. |
| Coverage analytics | Not implemented. There is no coverage endpoint or service that identifies geographic gaps or repeated unresolved reports. |
| Report resolution | Staff can list reports across restrooms and update report status through the Gateway; check the current route table and Postman collection for role requirements. |
| Automation/deployment | The Postman collection is `SaniMap.postman_collection.json` at the repository root. Railway setup and post-deployment JMeter instructions are in [the Railway guide](railway-deployment-jmeter.md). CI still needs to be configured. |

## 2. Prerequisites

Install Python 3.10+ and Node.js 18+ (including npm). Install Postman for API checks. Install Apache JMeter only when the local/staging functional tests pass.

Open a PowerShell terminal at the repository root:

```powershell
Set-Location "<path-to-your-cloned-SaniMap-repository>"
```

Create and activate a Python virtual environment, then install backend dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r gateway\requirements.txt
```

If PowerShell blocks activation, allow scripts only for the current terminal with `Set-ExecutionPolicy -Scope Process Bypass`, then activate the environment again.

## 3. Configure local environment

Create your own local `.env` and `frontend/.env.local` from the example
templates. Until the frontend file sets `VITE_USE_MOCK_API=false`, the UI uses
mock data and does not prove backend connectivity.

1. Create the backend `.env` from the repository-root template:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Generate a random JWT secret and copy its output into `JWT_SECRET` in `.env`:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Keep `JWT_ISSUER=sanimap-gateway` and `JWT_AUDIENCE=sanimap-api` the same in `.env` and generated tokens. The gateway refuses to start if the secret is missing/short or issuer/audience are blank. Do not commit `.env`, tokens, or API keys.

3. For local services, keep the default URLs:

   ```text
   SANIMAP_REGISTRY_URL=http://127.0.0.1:5001
   SANIMAP_REPORTING_URL=http://127.0.0.1:5002
   ```

   The Reporting Service uses `SANIMAP_REGISTRY_URL` to check that a restroom exists before saving a report. The gateway uses both URLs to route requests and check backend health.

   These are API base URLs, not web pages; opening `http://127.0.0.1:5002/` directly returns 404 because the service has no root route. To check the service in a browser, open `http://127.0.0.1:5002/health` and confirm it returns HTTP 200 with `"status": "UP"`.

4. Directions need a valid `ORS_API_KEY`; without it, `/directions` deliberately responds with HTTP 503. Geocoding uses the public Nominatim service and needs a meaningful `SANIMAP_CONTACT_EMAIL` for its user agent. These are optional for the core restroom/report flow.

5. Create the frontend's local environment file and confirm it points at the local gateway:

   ```powershell
   Copy-Item frontend\.env.example frontend\.env.local
   ```

   In `frontend\.env.local`, set:

   ```text
   VITE_USE_MOCK_API=false
   VITE_API_BASE_URL=/api
   SANIMAP_GATEWAY_URL=http://127.0.0.1:5000
   ```

   Vite reads frontend variables when it starts, so restart Vite after changing them. Never put `JWT_SECRET`, `ORS_API_KEY`, or any other backend secret in a `VITE_` variable or frontend file.

## 4. Start the services

Run each command in a separate PowerShell terminal from the repository root. Start the Registry first because the Reporting Service calls it.

Before starting, check whether the default ports are already in use:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 5000, 5001, 5002 } |
  Select-Object LocalPort, OwningProcess
```

If a port is busy, inspect the owning process with `Get-Process -Id <OwningProcess>`. Stop it only from the terminal that started it and only if you recognize it; do not terminate an unknown process. During this repository check, all three default ports were occupied by Python processes. Their gateway returned restroom records with snake_case fields and non-Luneta IDs, unlike this checkout's camelCase fields and Luneta seed data. A green `/health` response alone therefore did not verify that the live listeners were this checkout.

If you own the existing processes, stop them normally and use the default commands below. Otherwise run this checkout on free ports with isolated databases. For example:

```powershell
# Registry terminal
$env:SANIMAP_REGISTRY_DB = Join-Path $env:TEMP "sanimap-registry-local-test.db"
python -m flask --app services.service_a.App_ServiceA:app run --host 127.0.0.1 --port 5101

# Reporting terminal
$env:SANIMAP_REGISTRY_URL = "http://127.0.0.1:5101"
$env:SANIMAP_REPORTING_DB = Join-Path $env:TEMP "sanimap-reporting-local-test.db"
python -m flask --app services.service_b.App_ServiceB:app run --host 127.0.0.1 --port 5102

# Gateway terminal
$env:SANIMAP_REGISTRY_URL = "http://127.0.0.1:5101"
$env:SANIMAP_REPORTING_URL = "http://127.0.0.1:5102"
$env:GATEWAY_PORT = "5100"
python gateway\App_Gateway.py
```

For this alternate-port setup, use `http://127.0.0.1:5100` as Postman's `baseUrl` and `SANIMAP_GATEWAY_URL` in `frontend/.env.local`. Use the matching Registry/Reporting URLs when checking their health. The file-based test databases remain in the system temp folder; do not point concurrent services at the same SQLite file.

**Terminal 1 — Registry Service (port 5001):**

```powershell
.\.venv\Scripts\Activate.ps1
python -m flask --app services.service_a.App_ServiceA:app run --host 127.0.0.1 --port 5001
```

**Terminal 2 — Reporting Service (port 5002):**

```powershell
.\.venv\Scripts\Activate.ps1
python -m flask --app services.service_b.App_ServiceB:app run --host 127.0.0.1 --port 5002
```

**Terminal 3 — API Gateway (port 5000):**

```powershell
.\.venv\Scripts\Activate.ps1
python gateway\App_Gateway.py
```

The Registry and Reporting services create their SQLite databases and seed demo records on first startup. The Flask commands above are for local development only, not production.

Check each component before opening the frontend:

```powershell
Invoke-RestMethod http://127.0.0.1:5001/health
Invoke-RestMethod http://127.0.0.1:5002/health
Invoke-RestMethod http://127.0.0.1:5000/health
Invoke-RestMethod http://127.0.0.1:5000/restrooms
```

The first three responses should have `"status": "UP"`. The restroom list should contain seeded records with integer `restroomId` values (initially 1 and 2).

Create a short-lived staff token in another terminal. The token output is sensitive: copy it directly to a local Postman variable or the frontend's staff-token prompt; do not paste it into source code, Git, or chat.

```powershell
.\.venv\Scripts\Activate.ps1
python tools\make_token.py admin --minutes 30
python tools\make_token.py park_manager --minutes 30
```

## 5. Test the API in Postman

1. In Postman choose **Import → File**, then import
   `SaniMap.postman_collection.json` from the repository root.
2. Open the collection's variables and set:
   - `baseUrl` = `http://127.0.0.1:5000`
   - `adminToken` = the token generated with role `admin`
   - `managerToken` = the token generated with role `park_manager`
   - Leave `restroomId` at `1` for the seed record. `reportId` starts at `501` for the demo report.
3. Run the collection in order, or run the requests individually:
   - **Gateway health** and **List restrooms** are public and should return HTTP 200.
   - **All services health** requires a manager or admin token; it should return HTTP 200 and both service statuses `UP`.
   - **Get restroom** should return HTTP 200 for ID 1.
   - **Create restroom** and **Update restroom status** require an admin token. A valid create request returns HTTP 201; update returns HTTP 200.
   - **Submit feedback** is public and returns HTTP 201; its test saves the created `reportId` for the lookup request.
   - **Feedback history** requires a manager or admin token. **Get report** is public.
   - **Invalid feedback** deliberately sends an invalid type and should return HTTP 400.
   - **Geocode** calls Nominatim and is subject to its rate limits. **Walking directions** requires `ORS_API_KEY` and may return HTTP 503 when that optional integration is not configured.
4. For authorization checks, remove the token from a protected request and expect HTTP 401. Use a `park_manager` token on **Create restroom** or **Update restroom status** and expect HTTP 403. `park_manager` is permitted to read health and feedback history.
5. For service-to-service failure checking, stop the Registry and retry **Submit feedback**: expect HTTP 503 and no new report. Start the Registry again afterward.

The gateway applies in-memory rate limits per client IP and globally: feedback is limited to 5 requests/minute per IP; geocoding is limited to 5/minute per IP; directions is limited to 10/minute per IP and 30/minute globally. Repeatedly running the collection may temporarily return HTTP 429.

### Current gateway endpoints

| Method and path | Access | Purpose |
| --- | --- | --- |
| `GET /health` | Public | Gateway process health only. |
| `GET /health/all` | Admin or park manager | Aggregated registry/reporting health; HTTP 503 if either is down. |
| `GET /restrooms` | Public | List restroom records. |
| `POST /restrooms` | Admin | Add a restroom. |
| `GET /restrooms/{restroomId}` | Public | Read a restroom. |
| `PUT /restrooms/{restroomId}/status` | Admin | Set `open`, `closed`, or `under_maintenance`. |
| `POST /feedback` | Public | Create a report; report type must be `UNSANITARY_FACILITY`, `CLEANLINESS`, `DAMAGED_FIXTURE`, `OUT_OF_WATER`, `CLOSED`, or `OTHER`. |
| `GET /feedback` | Admin or park manager | List reports across facilities with supported filters and pagination. |
| `GET /feedback/{restroomId}` | Admin or park manager | List reports for one restroom. |
| `GET /feedback/reports/{reportId}` | Public | Read one report. |
| `PUT /feedback/reports/{reportId}/status` | Admin or park manager | Set report status to `PENDING`, `RESOLVED`, or `REJECTED`. |
| `GET /geocode?q={query}` | Public | Search a place using Nominatim. |
| `GET /reverse-geocode?lat={lat}&lon={lon}` | Public | Reverse-geocode coordinates. |
| `GET /directions?start_lat={lat}&start_lng={lng}&end_lat={lat}&end_lng={lng}&profile=foot-walking` | Public | Get a walking route using OpenRouteService. |

Restroom creation JSON fields are `name`, `latitude`, `longitude`, `operatingHours`, `pwdAccessible`, `genderType`, `amenities`, and `status`. Feedback creation JSON fields are `restroomId`, `reportType`, and optional `description`. Requests default to JSON; registry and reporting services also support XML using `Accept: application/xml`.

## 6. Run automated tests and frontend checks

From the repository root, with the Python virtual environment active:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

The tests cover gateway forwarding/authentication, service validation, XML/JSON handling, database persistence, and health checks. Run a frontend production build in a separate terminal:

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
```

The generated frontend bundle is in `frontend\dist`. The local Vite dev server is not a production server.

## 7. Test the frontend against the API

With the three backend services running and the frontend `.env.local` set to live mode:

```powershell
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). Confirm that the restroom list comes from the API, submit a test report, and check it appears in the staff report view with an admin or manager token. In browser developer tools, requests should go to `/api/...`; a failed gateway call must not silently be treated as a successful live request.

If data appears even though the backend is stopped, check that `VITE_USE_MOCK_API=false` is set and restart Vite. Mock mode stores changes in browser `localStorage`, not SQLite.

## 8. JMeter load and failure testing

Use JMeter only against localhost or an authorized staging deployment. Do not run load/failure tests against production or the public Nominatim/OpenRouteService services without explicit approval. Keep geocoding and directions out of load tests so that third-party quotas and terms are not affected.

1. Start with the Postman checks and unit tests passing.
2. Create a JMeter **Test Plan** with a **Thread Group** and HTTP Request Defaults:
   - Server: `127.0.0.1`
   - Port: `5000`
   - Protocol: `http`
3. Add an **HTTP Header Manager** with `Accept: application/json`. Add a **CSV Data Set Config** only if using multiple IDs/tokens. Do not commit real staff tokens.
4. Add low-rate sampler requests for:
   - `GET /health` (gateway only)
   - `GET /restrooms`
   - `GET /restrooms/1`
   - Optionally `GET /feedback/reports/501`
5. Add **Response Assertions** for expected status codes and a **Duration Assertion** only after agreeing on an acceptable response-time objective. Add a Summary Report/Aggregate Report listener. Start with 1 user and a 1-second ramp-up; record a baseline before increasing concurrency gradually.
6. Keep writes in a separate, short test. `POST /feedback` is rate-limited to 5/minute per IP; stop if requests return 429 or backend error rates increase. SQLite is suitable for this small demo, not a high-concurrency production write workload.
7. Failure test in local/staging: with Registry and Reporting running, stop one backend and query `GET /health/all` using a staff token. It should return HTTP 503 and show the affected service as `DOWN`. Submit feedback while the Registry is stopped; it should return HTTP 503. Restart the backend and confirm health returns to HTTP 200.
8. Save the JMeter `.jmx` plan and exported results only if your team needs them, and redact tokens/PII before sharing results. Report throughput, error percentage, and response-time percentiles alongside the hardware, environment, thread count, and ramp-up settings.

Do not interpret JMeter error percentages without checking whether the test hit an intentional rate limit, missing ORS key, or stopped service.

## 9. Coverage and monitoring work still required

Geographic coverage-gap analysis is not implemented. Before adding it, agree on
the study boundary, how reach is measured (for example walking distance or
time), and what counts as a coverage gap. Before flagging repeated unresolved
reports, agree on the report window and threshold. Do not invent these values
in production logic. Railway deployment healthchecks verify startup; add an
external uptime monitor if continuous alerting is required.

Recommended implementation sequence:

1. Define the coverage boundary, measurement, and thresholds with stakeholders.
2. Implement coverage/monitoring data that combines registry locations and
   report records, with documented thresholds and source timestamps.
3. Add tests for threshold boundaries, resolved reports, empty data, invalid
   filters, and registry/reporting outages.
4. Expose the capability through an authenticated Gateway route and add it to
   the Postman collection.
5. Add continuous health monitoring and alerts. Do not treat `GET /health` as a
   full-system readiness check.

## 10. CI and cloud deployment checklist

Railway service configuration, root directories, build/start commands, runtime
variables, volumes, CORS, healthchecks, Postman smoke tests, and a post-deploy
JMeter plan are documented in [Railway deployment and JMeter](railway-deployment-jmeter.md).
Use a feature branch and staging environment. A GitHub Actions CI workflow is
not included yet; add one before making successful automated checks a required
branch-protection rule.