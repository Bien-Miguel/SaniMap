# SaniMap React frontend

React + Vite visitor map and staff dashboard for the SaniMap API. The app uses
integer `restroomId` values, camelCase fields, and JSON by default.

## Local development

Install Node.js 18+ and npm, then from the repository root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

Mock mode is enabled by default and uses Luneta seed facilities plus sample
reports in browser `localStorage`. It does not grant staff access. The staff
dashboard always requires a token accepted by the live Gateway, including
when visitor data is mocked. To use the live local Gateway, copy
`frontend\.env.example` to `frontend\.env.local`, set
`VITE_USE_MOCK_API=false`, and restart Vite. Vite proxies `/api` to the
Gateway, so the local browser requests remain same-origin.

## Features and staff permissions

The map uses Leaflet with OpenStreetMap tiles and visible attribution. The app
supports browsing and filtering facilities, reporting issues, report lookup,
staff report history, and staff status updates. Walking directions require the
live Gateway and a valid server-side `ORS_API_KEY`; never put that key in the
frontend.

Public routes allow facility browsing, report submission, and report lookup.
Staff routes require an externally issued JWT with an `admin` or
`park_manager` role. The frontend validates staff tokens through the protected
Gateway `/auth/verify` endpoint; the Gateway is the authority for token
signature and role validation. This project does not implement staff login or
token issuance. Facility creation and facility status updates require `admin`;
report history, aggregate health, and report-status updates allow both staff
roles.

## Production deployment

The production frontend is a Vite build served by `server.mjs` (not Vite's
development or preview server). On Render, set the frontend service's root to
`/frontend`, build with `npm ci && npm run build`, and start with
`node server.mjs`.

At build time, set `VITE_USE_MOCK_API=false` and
`VITE_API_BASE_URL=https://<gateway-domain>`. Configure the Gateway's
`SANIMAP_CORS_ORIGINS` to the exact HTTPS frontend origin. Vite embeds every
`VITE_` value into public browser assets; never put keys, signing secrets, or
staff tokens in them. If the API URL is missing or returns the frontend HTML
instead of JSON, API calls fail closed rather than treating that response as
successful authentication. Safe GET requests retry temporary network failures
and 502/503/504 responses with bounded backoff; mutations are never retried
automatically except feedback submissions carrying a request idempotency key.
The Reporting Service stores that key with the report so a retry returns the
original receipt rather than creating a duplicate.

Render free web services spin down after inactivity and can take about a minute
or longer to start again. The frontend keeps the facility list loading and
retries temporary failures for roughly 87 seconds before showing an error. The public Gateway
`/health` endpoint checks only the Gateway; the Registry's own `/health`
endpoint checks the Registry. A request to Gateway `/restrooms` exercises both
services. Do not use frequent health pings as a substitute for an always-on
plan.

The Registry currently uses SQLite. On Render, a local SQLite database on a
free web service is ephemeral and can be lost when the service spins down,
restarts, or redeploys. The five built-in Luneta facilities are reseeded when
the Registry starts, but other facilities added by staff can still disappear.
Free Render web services cannot attach persistent disks. To preserve all
SQLite data, upgrade the Registry service to a paid plan,
attach a persistent disk mounted at `/var/data`, and set
`SANIMAP_REGISTRY_DB=/var/data/registry.db`. Alternatively, migrate the
Registry to a managed database and update the application to use it.

See the [Registry service README](../services/service_a/README.md) for its
database configuration and Render persistence notes.
