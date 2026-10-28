# Render deployment guide

This guide deploys the three business services, Gateway, and Frontend from
this repository. Keep Registry, Reporting, Maintenance, and Gateway in the
same Render region so they can use private service-to-service URLs.

## Create the services

Create five services from the same GitHub repository and branch. The
application is under `SaniMap-feature-frontend-map/`, so set each Root
Directory to the path shown below (relative to the Git repository root).

| Render service | Type | Root Directory | Build command | Start command |
| --- | --- | --- | --- | --- |
| `sanimap-registry` | Private Service | `SaniMap-feature-frontend-map/services/service_a` | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_ServiceA:app` |
| `sanimap-reporting` | Private Service | `SaniMap-feature-frontend-map/services/service_b` | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_ServiceB:app` |
| `sanimap-maintenance` | Private Service | `SaniMap-feature-frontend-map/services/service_c` | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_ServiceC:app` |
| `sanimap-gateway` | Web Service | `SaniMap-feature-frontend-map/gateway` | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_Gateway:app` |
| `sanimap-frontend` | Web Service | `SaniMap-feature-frontend-map/frontend` | `npm ci && npm run build` | `node server.mjs` |

Set `/health` as the health check path for each Python service. The Frontend
health check path is `/`. Do not create public URLs for the three private
business services. Create public URLs for the Gateway and Frontend.

## Configure Registry

Add a persistent disk mounted at `/var/data`, then set:

```text
SANIMAP_REGISTRY_DB=/var/data/registry.db
```

## Configure Reporting

Add its own persistent disk mounted at `/var/data`. Set:

```text
SANIMAP_REPORTING_DB=/var/data/reporting.db
SANIMAP_REGISTRY_URL=<Registry internal URL>
```

Copy the Registry's internal URL from its Render service page. Reporting
depends on Registry to validate restroom IDs in visitor reports.

## Configure Maintenance (Service C)

Add a separate persistent disk mounted at `/var/data`, then set:

```text
SANIMAP_WORK_ORDERS_DB=/var/data/work_orders.db
SANIMAP_REPORTING_URL=<Reporting internal URL>
```

Copy the Reporting internal URL from its Render service page. Service C
validates each `reportId` against Reporting before creating a job, and stores
maintenance assignments, priorities, statuses, and change history in its own
database. It does not own restroom records or visitor reports.

## Configure Gateway

Set the JWT values below and use the internal URLs copied from the Registry,
Reporting, and Maintenance service pages:

```text
JWT_SECRET=<unique random secret of at least 32 characters>
JWT_ISSUER=sanimap-gateway
JWT_AUDIENCE=sanimap-api
SANIMAP_REGISTRY_URL=<Registry internal URL>
SANIMAP_REPORTING_URL=<Reporting internal URL>
SANIMAP_MAINTENANCE_URL=<Maintenance internal URL>
SANIMAP_CORS_ORIGINS=https://<Frontend public hostname>
```

Optionally set `ORS_API_KEY` for walking directions. Do not put backend secrets
or staff tokens in the Frontend environment. Generate a fresh secret, for
example with `python -c "import secrets; print(secrets.token_urlsafe(48))"`,
and store it only in Render's Gateway environment variables.

## Configure Frontend

Set these build-time environment variables:

```text
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=https://<Gateway public hostname>
```

Set `SANIMAP_CORS_ORIGINS` to the exact Frontend origin, with no trailing
slash. Redeploy the Frontend after changing either `VITE_` variable.

## Verify the service graph

1. Deploy Registry, then Reporting, then Maintenance; check each `/health`
   endpoint and confirm its disk is mounted.
2. Deploy Gateway after setting all three internal URLs. Use a short-lived
   staff token to call `GET /health/all`; the response must show
   `registry_service`, `reporting_service`, and `maintenance_service` as `UP`.
3. Submit visitor feedback through the Gateway, then create a work order using
   its `reportId`:

   ```json
   {
     "reportId": 501,
     "priority": "HIGH",
     "assignedTo": "Facilities team"
   }
   ```

4. With an admin or park-manager token, call `GET /work-orders`, update the
   job using `PUT /work-orders/{workOrderId}`, and confirm the changes appear
   in `GET /work-orders/{workOrderId}/history`.
5. Deploy Frontend and verify its live API traffic uses the Gateway domain.

Keep each SQLite-backed service to one instance and use its own persistent
disk. For production-scale concurrent writes or multiple replicas, migrate
the services to a managed database before scaling.
