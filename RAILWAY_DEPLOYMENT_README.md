# SaniMap Railway Deployment README

This is the deployment runbook for SaniMap. It covers which project files
belong in GitHub, which local files must stay private, Railway service setup,
environment variables, persistent databases, deployment verification, and a
safe post-deployment JMeter plan.

Railway is compatible with this project. **Docker is not required**: Railway
can build the Python services and React/Vite frontend with Railpack. Use
Docker only if you later need custom operating-system packages or a
fully-controlled container image.

Deploy to a Railway staging environment first. Do not use a load test to
validate an unreviewed production deployment.

## 1. Files to upload and files to keep local

Commit the application source and the runtime manifests needed to build each
service. The repository is a monorepo; Railway's **Root Directory** setting
isolates each service's build context.

| Railway service | Required source and dependency files |
| --- | --- |
| Registry | `services/service_a/App_ServiceA.py`, `services/service_a/requirements.txt` |
| Reporting | `services/service_b/App_ServiceB.py`, `services/service_b/requirements.txt` |
| Gateway | `gateway/App_Gateway.py`, `gateway/requirements.txt` |
| Frontend | `frontend/package.json`, `frontend/package-lock.json`, `frontend/index.html`, `frontend/vite.config.js`, `frontend/server.mjs`, and `frontend/src/` |

Also keep the root `requirements.txt` for local development and CI, the tests
and seed/token utility scripts, `.env.example` templates, `.gitignore`, the
GitHub Actions workflow, the Postman **collection**, and the project
documentation. The Railway build uses each service's own dependency manifest;
it does not need the developer's installed dependencies.

GitHub receives files that are committed to the selected branch. Railway uses
the configured service root for each build; the entire repository is not
copied into every service image. README and test files are useful in GitHub
but are not runtime dependencies of the deployed services.

The repository also contains a pre-existing tracked legacy project directory,
`SaniMap_group2_Lab6-main/`. It is outside all four Railway service roots, so
it is not part of these service build contexts. `.gitignore` cannot hide files
that are already tracked; avoid staging unrelated edits to this directory.

Do **not** commit:

- `.env`, `frontend/.env.local`, or any other real environment file. Commit
  only the blank/sample `.env.example` templates.
- `ORS_API_KEY`, `JWT_SECRET`, staff bearer tokens, passwords, or exported
  Postman environments containing secrets.
- Python virtual environments (`venv/`, `.venv/`), `__pycache__/`, `.pyc`
  files, `node_modules/`, or the generated `frontend/dist/` build output.
- Local SQLite databases (`*.db`, `*.sqlite`, `*.sqlite3`) and SQLite
  `-wal`/`-shm` sidecars.
- Test/coverage output, logs, JMeter result files, and local JMeter reports.
- Editor/OS-specific files such as `.vscode/`, `.DS_Store`, and `Thumbs.db`.

The root and frontend `.gitignore` files exclude these local artifacts while
allowing the safe `.env.example` templates. Verify ignore behavior before
committing:

```powershell
git check-ignore -v .env frontend/.env.local frontend/node_modules frontend/dist services/service_a/registry.db
git status --short
git diff --cached --name-only
```

`.gitignore` does not untrack a file already committed. If a real credential
was ever committed or pushed, revoke/rotate it with its issuer; deleting it
later does not remove it from Git history.

## 2. Select the deployment branch and run local checks

Use the reviewed feature branch for staging. Do not deploy `main` until the
feature branch is reviewed and you explicitly choose to merge it.

```powershell
git switch feature/railway-deployment
git status --short
```

Install dependencies locally and run the checks from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend ci
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
npm --prefix frontend run build
```

Review the exact branch and staged file list before pushing:

```powershell
git branch --show-current
git status --short
git add -A
git diff --cached --check
git diff --cached --name-only
git commit -m "Add Railway deployment README"
git push -u origin feature/railway-deployment
```

Before committing, confirm the branch name is `feature/railway-deployment` and
the staged list contains only intended source and documentation. Do not add
real environment files, databases, generated dependency folders, or unrelated
changes. Open a pull request against the agreed integration branch; do not
merge or push directly to `main` before review and deployment checks pass.

## 3. Create the Railway project and services

1. In Railway, create a project from the GitHub repository and choose the
   `feature/railway-deployment` branch for staging.
2. Add four services from the same repository. Give them these exact names so
   the variable references below work: `Registry`, `Reporting`, `Gateway`,
   and `Frontend`.
3. Use each service's **Root Directory** to isolate its build context:

   | Railway service | Root Directory |
   | --- | --- |
   | Registry | `/services/service_a` |
   | Reporting | `/services/service_b` |
   | Gateway | `/gateway` |
   | Frontend | `/frontend` |

4. Use the following build and start commands in each service's Deploy
   settings. Railway's `$PORT` is injected at runtime; each process must bind
   to `0.0.0.0` and that port.

   | Service | Build command | Start command | Healthcheck path |
   | --- | --- | --- | --- |
   | Registry | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_ServiceA:app` | `/health` |
   | Reporting | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_ServiceB:app` | `/health` |
   | Gateway | `pip install -r requirements.txt` | `gunicorn --bind 0.0.0.0:$PORT App_Gateway:app` | `/health` |
   | Frontend | `npm ci && npm run build` | `node server.mjs` | `/` |

   These commands run on Railway's Linux build environment. Keep Flask debug
   mode disabled. The frontend's `server.mjs` serves the Vite build, supports
   client-side routes such as `/map` and `/admin`, and listens on Railway's
   `PORT`.

## 4. Configure Railway environment variables and private networking

Add variables in the **Variables** panel for the specific Railway service
below, never in GitHub, a committed `.env`, or a frontend `VITE_` secret.
Railway variable references use `${{ServiceName.VARIABLE}}`; backend
service-to-service traffic uses the private DNS domain and HTTP. Railway
provides `PORT` for each service; do not hard-code it or set a different port.

Keep the root `.env` for local development only. `.env.example` is a
non-secret template and documents local defaults; it is not automatically
loaded by Railway. Set production variables in Railway's dashboard.

### Registry

```text
SANIMAP_REGISTRY_DB=/data/registry.db
```

Attach a Railway Volume to this service with mount path `/data`.

### Reporting

```text
SANIMAP_REPORTING_DB=/data/reporting.db
SANIMAP_REGISTRY_URL=http://${{Registry.RAILWAY_PRIVATE_DOMAIN}}:${{Registry.PORT}}
```

Attach a separate Railway Volume to this service with mount path `/data`.

### Gateway

```text
JWT_SECRET=<a new random secret of at least 32 characters>
JWT_ISSUER=sanimap-gateway
JWT_AUDIENCE=sanimap-api
SANIMAP_REGISTRY_URL=http://${{Registry.RAILWAY_PRIVATE_DOMAIN}}:${{Registry.PORT}}
SANIMAP_REPORTING_URL=http://${{Reporting.RAILWAY_PRIVATE_DOMAIN}}:${{Reporting.PORT}}
SANIMAP_CORS_ORIGINS=https://${{Frontend.RAILWAY_PUBLIC_DOMAIN}}
ORS_API_KEY=<your OpenRouteService key, optional>
```

Generate a fresh production JWT secret using a trusted password generator or
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. Do not reuse
the local development secret. The ORS key is optional and is needed only for
walking directions. Keep both values exclusively in Railway's Gateway
variables. If you set or rotate `JWT_SECRET`, issue new staff tokens that use
that production secret, issuer, and audience.

### Frontend

```text
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=https://${{Gateway.RAILWAY_PUBLIC_DOMAIN}}
```

Vite embeds `VITE_` values in public browser code at build time; the Gateway
URL is public configuration, not a secret. Never put `JWT_SECRET`,
`ORS_API_KEY`, database URLs with credentials, or staff tokens in a `VITE_`
variable. Redeploy the Frontend after changing either build variable.

The `SANIMAP_CORS_ORIGINS` value must exactly match the Frontend's HTTPS origin
(no trailing slash). If you use a custom domain, update this variable to that
origin and redeploy the Gateway.

## 5. Set up persistent databases, deploy, and verify

1. Deploy Registry and Reporting. Confirm each Railway deployment is healthy
   at `/health`.
2. Confirm both volumes are mounted at `/data`, then verify each service
   starts without a database-path error. Keep each SQLite service at one
   replica; SQLite on a volume is not a multi-replica database.
3. Deploy Gateway. Confirm `/health` succeeds. The Gateway must reach the
   Registry and Reporting URLs over Railway private networking. Do not create
   public domains for either backend service.
4. Generate a public Railway domain only for Gateway and Frontend. If the
   domain variable references were not available during the first deployment,
   set the final values in the variable panels and redeploy.
5. Deploy Frontend and visit its HTTPS URL. Directly load and refresh `/map`
   and `/admin`; both should return the application rather than a 404.
6. Open browser developer tools. Confirm API requests use the Gateway domain,
   do not fail with CORS errors, and return live Registry data (not mock data).
7. Confirm Gateway `/health/all` using a short-lived staff token. It should
   report both backend services as `UP`. Configure an external uptime monitor
   separately; Railway deployment healthchecks validate startup and are not
   continuous monitoring.

For SQLite data, test persistence by creating a disposable record/report,
redeploying the corresponding service, and reading it again. Review Railway
volume backup and restore procedures before real visitor data is accepted.
Do not scale SQLite-backed services horizontally. For sustained or
concurrent production writes, plan a migration to a managed database.

## 6. Post-deployment functional/API smoke checks

Import `SaniMap.postman_collection.json` into Postman. Set `baseUrl` to the
Gateway's HTTPS public URL. Keep the Postman environment local and uncommitted.
Use short-lived admin and manager tokens created for the deployed issuer,
audience, and secret; local tokens will not validate against production.

Run the collection and confirm the expected statuses:

| Request | Expected |
| --- | ---: |
| `GET /health` | 200 |
| `GET /health/all` without staff token | 401 |
| `GET /health/all` with admin or manager token | 200; both services `UP` |
| `GET /restrooms` | 200 |
| `GET /feedback` without staff token | 401 |
| `GET /feedback` with staff token | 200 |
| Invalid registry/report payload | 400 |
| Manager attempts admin-only restroom creation | 403 |
| Unknown restroom/report ID | 404 |
| `GET /directions?...` | 200 when ORS is configured; otherwise documented 503 |

Run the write requests only once or with disposable test records. Do not use
JMeter for writes or third-party integrations unless you have a separate,
approved test plan.

## 7. Build a safe JMeter read-only test plan

Use JMeter against staging or an environment you own. Do not run load tests
against production, Nominatim, or OpenRouteService without explicit approval.
The starter plan below performs only three Gateway reads and does not require
staff tokens or create data.

1. Create a new **Test Plan** and add a **User Defined Variables** element.
   Use JMeter property functions so the same plan can run in GUI and non-GUI
   mode:

   | Name | Value |
   | --- | --- |
   | `protocol` | `${__P(protocol,https)}` |
   | `gatewayHost` | `${__P(gatewayHost,your-gateway.up.railway.app)}` (host only; no scheme/path) |
   | `restroomId` | `${__P(restroomId,1)}` |

2. Add a **Thread Group**. Start with **5 users (threads)**, **30 seconds
   ramp-up**, and **5 loops**. This is a baseline of 25 iterations; each
   iteration sends three reads.
3. Add **HTTP Request Defaults** below the Thread Group:
   - Protocol: `${protocol}`
   - Server Name or IP: `${gatewayHost}`
   - Leave Port blank for standard HTTPS.
4. Add an **HTTP Header Manager** with `Accept: application/json`.
5. Add three **HTTP Request** samplers (method `GET`):
   - Path `/health`
   - Path `/restrooms`
   - Path `/restrooms/${restroomId}`
6. Add a **Response Assertion** to each sampler. Set the field to **Response
   Code** and require it to equal `200`.
7. Add **Summary Report** and **Aggregate Report** listeners. Use **View
   Results Tree** only for a one-user diagnostic run; it adds overhead and
   should not be used to measure throughput.
8. Create `jmeter-results` and save the plan as
   `jmeter-results/sanimap-staging-readonly.jmx`. The root `.gitignore`
   excludes this local test-plan/results directory.
9. Run the baseline in JMeter GUI. Confirm every sample passes and record
   sample count, throughput, error rate, median, 90th and 95th percentile
   latency, thread count, ramp-up, and the Railway plan/region.
10. Only if the baseline is healthy, repeat gradually with 10 users and then
    20 users, increasing ramp-up time as needed. Stop immediately for rising
    5xx errors, unexpected 429s, database errors, or resource/usage warnings.
    There is no universal performance threshold: compare results to your
    product's agreed service-level objectives.

For repeatable non-GUI execution, use JMeter properties in the **Test Plan**
variables and keep the host and test data on the command line:

```powershell
jmeter -n -t .\jmeter-results\sanimap-staging-readonly.jmx `
  -Jprotocol=https `
  -JgatewayHost=your-gateway.up.railway.app `
  -JrestroomId=1 `
  -l .\jmeter-results\baseline.jtl `
  -e -o .\jmeter-report\baseline
```

Create the `jmeter-results` directory first; the HTML report output directory
must not already exist. Store and share results only after removing
tokens, personal data, and private host details as appropriate.

The read-only JMeter test does **not** replace the functional Postman suite.
Use Postman for JWT/RBAC, validation, feedback submission, report status
changes, and data-persistence checks. Exclude `/directions` and geocoding from
load tests so they do not consume external-provider quotas.

## 8. Docker, scaling, and deployment boundaries

Docker is not needed for the four Railway Railpack deployments described here.
Use Docker only if you need reproducible custom images or system-level
dependencies not supplied by Railpack.

This deployment uses one Railway service and one persistent volume per
SQLite-backed service. It is a small-deployment starting point, not a
high-availability database architecture. Keep databases backed up, restrict
public exposure to Gateway and Frontend, and move to a managed database before
scaling write traffic or replicas.
