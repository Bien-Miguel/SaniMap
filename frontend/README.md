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
`park_manager` role. This project does not implement staff login or token
issuance. Facility creation and facility status updates require `admin`;
report history, aggregate health, and report-status updates allow both staff
roles.

## Production deployment

Railway serves the Vite build using `server.mjs` (not Vite's development or
preview server). Set the frontend service's root to `/frontend`, build with
`npm ci && npm run build`, and start with `node server.mjs`.

At build time, set `VITE_USE_MOCK_API=false` and
`VITE_API_BASE_URL=https://<gateway-domain>`. Configure the Gateway's
`SANIMAP_CORS_ORIGINS` to the exact HTTPS frontend origin. Vite embeds every
`VITE_` value into public browser assets; never put keys, signing secrets, or
staff tokens in them.

See the [Railway deployment README](../RAILWAY_DEPLOYMENT_README.md)
for the full setup and verification steps.
