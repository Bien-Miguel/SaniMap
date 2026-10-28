# SaniMap

SaniMap is a Luneta Park comfort-room finder with a React map, three distinct
business services (Registry, Reporting, and Maintenance), and a JWT-protected
API Gateway.

## Project structure

| Path | Purpose |
| --- | --- |
| `frontend/` | React/Vite visitor map and staff dashboard |
| `gateway/` | Public API entry point, authorization, routing, and external API integrations |
| `services/service_a/` | SQLite-backed restroom Registry |
| `services/service_b/` | SQLite-backed visitor Reporting service |
| `services/service_c/` | SQLite-backed maintenance work orders and event history |
| `tests/` | Python unit and integration tests |
| `tools/` | Local seed and short-lived staff-token utilities |
| `SaniMap.postman_collection.json` | Postman API smoke and integration requests |
| `docs/` | Setup, testing, Railway deployment, and JMeter guidance |

## Local development

Use Python 3.10+ and Node.js 18+ with npm. From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
npm --prefix frontend ci
```

Copy `.env.example` to `.env`, provide a random `JWT_SECRET` (at least 32
characters), and fill in the optional ORS key only if you want directions.
Never commit `.env`, staff tokens, or API keys.

Start the Registry (`python services\service_a\App_ServiceA.py`), Reporting
(`python services\service_b\App_ServiceB.py`), Maintenance
(`python services\service_c\App_ServiceC.py`), and Gateway
(`python gateway\App_Gateway.py`) in separate terminals. The Maintenance
Service validates each new work order against Reporting; the Gateway routes
staff work-order requests to it. Start the frontend with
`npm --prefix frontend run dev`. For a connected local frontend, copy
`frontend\.env.example` to `frontend\.env.local` and set
`VITE_USE_MOCK_API=false`.

Run the checks:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
npm --prefix frontend run build
```

## Deployment

Docker is optional. Railway can build each service from its subdirectory using
Railpack. Configure five Railway services (Gateway, Registry, Reporting,
Maintenance, and Frontend), persistent volumes for all three SQLite services,
and secret variables in Railway—not in source control.

Follow the [Railway deployment and post-deployment JMeter guide](docs/railway-deployment-jmeter.md)
for exact service roots, build/start commands, variables, health checks, data
persistence, and a cautious staging test plan. The
[local setup and API testing guide](docs/testing-deployment-guide.md) covers
service and Postman checks. For Render configuration, private service
connections, and persistent disks, see the [Render deployment guide](docs/render-deployment.md).

## Important limitations

- Staff tokens are issued outside this project. The app does not provide a
  login or token-issuing endpoint.
- Walking directions require a valid server-side `ORS_API_KEY`; it must never
  be added to a `VITE_` variable.
- SQLite with one replica per service is suitable for this demonstration.
  Review database, backup, and scaling needs before production traffic.
