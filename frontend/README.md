# SaniMap React frontend

React + Vite visitor map and staff dashboard for the current SaniMap Gateway. This frontend follows the root service README contracts (integer `restroomId`, camelCase fields, JSON by default); it does not use the older lab demo APIs.

## Start in mock mode

Mock mode is enabled by default and uses Luneta restroom seed records plus sample reports. Changes are kept in browser `localStorage`, so you can develop the map, report workflow, and admin screens without starting the backend.

```powershell
cd .\frontend
npm install
npm run dev
```

The map uses Leaflet with OpenStreetMap tiles and visible attribution. Mock mode supports browsing, filters, creating reports, report lookup, adding a facility, and changing facility status. Walking directions require the live Gateway and an `ORS_API_KEY` configured on the Gateway; provider keys must never be put in the frontend.

## Connect to the live backend

1. Start the Registry Service, Reporting Service, and API Gateway as described in the root/service READMEs.
2. Copy `.env.example` to `.env.local` and set `VITE_USE_MOCK_API=false`. Optionally set `SANIMAP_GATEWAY_URL` if the Gateway is not at `http://127.0.0.1:5000`.
3. Restart Vite. The development server proxies `/api` requests to the Gateway, avoiding a browser CORS dependency during local development.

The visitor map and report submission use public Gateway routes. Staff routes require a valid Gateway-issued Bearer JWT; paste an already-issued token in the dashboard prompt. The token must carry the required `admin` or `park_manager` role. No login/token-issuance API is included. Creating facilities and updating status require `admin`; report history and aggregated service health allow `admin` or `park_manager`. Reports are read-only because the current backend has no report status update operation.

For production, set `VITE_API_BASE_URL` to the deployed same-origin Gateway path (or configure CORS separately), and issue/authenticate staff tokens outside the frontend. Do not ship secrets or long-lived tokens in the client bundle.
