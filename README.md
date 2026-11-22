# Service Deployment Toolkit

A Python CLI for deploying and recovering a local Docker Compose service. The
demo runs a FastAPI catalogue backed by PostgreSQL and served through NGINX.
The toolkit replaces the API by immutable image ID and verifies the running
release and catalogue through both HTTP routes.

| Workflow | What it checks or records |
|---|---|
| Deploy | Checks resource ownership, records intent, and verifies the API image, release and database-backed response. |
| Manual rollback | Restores a compatible release selected by its full operation ID. Preview is available. |
| Automatic recovery | With explicit opt-in, verifies a running baseline and can restore it once after a confirmed candidate fails verification. |
| Reconciliation | Inspects a pending operation and lets the operator explicitly close it as unknown. |

The demo was exercised locally on EndeavourOS x86_64 with Python 3.14.10,
Docker Engine 29.9.3 and Compose 5.7.1. Recorded live runs cover deployment,
manual rollback, reconciliation after controlled toolkit exits and one opt-in
automatic recovery after a candidate failed to start serving HTTP.
[Phase 3 verification](docs/PHASE-3-RECOVERY.md#combined-live-results)

## Run the demo

Use Linux, Python 3.14 and Docker Engine with Compose. The toolkit uses
the default local Docker socket at `/var/run/docker.sock`. First setup may
download the pinned images and packages. Run commands from the project root.

Check that ports 8088 and 8089 are free and that existing `sdt-demo` resources,
if any, belong to this checkout.

```bash
docker context show
ss -ltn '( sport = :8088 or sport = :8089 )'
docker ps -a --filter label=com.docker.compose.project=sdt-demo
docker volume ls --filter name=sdt-demo
docker network ls --filter name=sdt-demo
```

For a new demo, generate the two credentials listed in `.env.example`:

```bash
python - <<'PY'
import os
import secrets

fd = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    file.write(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n")
    file.write(f"APP_DB_PASSWORD={secrets.token_hex(24)}\n")
PY
```

The generator refuses an existing file. Keep the existing credentials and
named volume when resuming. On a fresh demo, build the API and load the three
catalogue records:

```bash
git check-ignore .env &&
docker compose config --quiet &&
docker compose build api &&
docker compose up -d --wait --wait-timeout 120 db &&
docker compose run --rm init &&
docker compose up -d --wait --wait-timeout 120 api nginx &&
python tests/smoke.py
```

The proxy uses `127.0.0.1:8088`, the direct API uses `127.0.0.1:8089` and
PostgreSQL uses the internal Compose network. The smoke script checks
`/health/live`, `/health/ready`, `/version` and `/items` on both HTTP routes.

Use `docker compose stop db api nginx` to pause the demo. To start existing
containers again, use Compose start so the stored API image is retained:

```bash
docker compose start --wait --wait-timeout 120 db api nginx
```

The documented smoke script expects the initial `demo-v1` release.

## Diagnose connectivity

Run `python -m toolkit diagnose` from the checkout with the existing demo.
It checks whether the API can resolve the database name and connect to the
database port, then reads the catalogue directly and through NGINX. Each line
shows the route, outcome and elapsed milliseconds. The command prints to the
terminal and leaves deployment state alone.
[Diagnostic scope and exit codes](docs/ARCHITECTURE.md#connectivity-diagnostics)

## Work with releases

Verify the running catalogue and record a compatible recovery baseline:

```bash
python -m toolkit status &&
python -m toolkit preflight --image sdt-demo-api:phase1 --release demo-v1 &&
python -m toolkit baseline --image sdt-demo-api:phase1 --release demo-v1 --schema catalogue-v1 &&
python -m toolkit targets
```

Use the recorded ID in place of `OPERATION_ID`. Preview checks current
eligibility. The actual rollback checks again before replacing the API.

```bash
python -m toolkit rollback --to OPERATION_ID --dry-run
python -m toolkit rollback --to OPERATION_ID
```

Deploy a separately built, trusted local image. Substitute its reference and
expected release. By default, a failed candidate is left available for
inspection or explicit manual rollback.

```bash
python -m toolkit deploy --image LOCAL_IMAGE --release EXPECTED_RELEASE
```

To opt in to automatic recovery, use the same deploy command with
`--auto-recover --schema catalogue-v1`. This requires a different image and
a strictly eligible, freshly verified running baseline. The deployment
returns exit `1` when the requested release fails, even if recovery restores
the previous release. Status shows the recorded recovery and its trigger.

The toolkit keeps its journal under the ignored `.runtime/toolkit/` directory.
For pending state, use `status` to get the ID and
`python -m toolkit reconcile --operation OPERATION_ID` to preview. Add
`--close-unknown` only after confirming any submitted Docker work has settled.
Closure records the current observation and preserves the previous verified
success. [Recovery rules and exit codes](docs/PHASE-3-RECOVERY.md#combined-batches-ce)

## Test and review

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip --require-virtualenv install -r requirements-dev.lock &&
PYTHONPATH=demo python -W error -m unittest discover -s tests &&
PYTHONPATH=demo python -O -W error -m unittest discover -s tests &&
python -m pip check
```

The [live recovery exercise](docs/PHASE-3-RECOVERY.md#combined-batch-live-acceptance)
uses the dedicated demo and intentionally interrupts the API.

- [Architecture and phase plan](docs/ARCHITECTURE.md)
- [Decisions](docs/DECISIONS.md)
- [Limitations and observed issues](docs/KNOWN-ISSUES.md)
- [Deployment verification](docs/PHASE-2-VERIFICATION.md)
- [Recovery verification](docs/PHASE-3-RECOVERY.md)
- [MIT license](LICENSE)
