# Service Deployment Toolkit

A local project for checking containerized releases and recovering from failed
deployments. The CLI validates inputs, inspects resources, and deploys or verifies
a local API image while recording the outcome. Recovery remains future work.
The demonstration workload is a small FastAPI catalogue, PostgreSQL, and NGINX.

## Current status

Phase 1 is merged. Phase 2 deployment is implemented and locally verified at
`fa8aaf1`; the Phase 2 branch is undergoing closure and PR review. All 153 tests
passed in normal and optimized modes on the owner's Python 3.14.10 environment.
Live exercises covered verification-only, stopped-API replacement, a different
candidate image, and explicit redeployment of the original image. No rollback
or reconciliation command exists yet.

The demo has been exercised on EndeavourOS x86_64 with Python 3.14.10,
Docker Engine 29.9.3, and Compose 5.7.1. These are tested versions, not a claim
that every other version is unsupported or compatible.

The original diet-recommendation API is not included or reused. A small
catalogue keeps the focus on deployment behavior rather than application features.

## Run the demo

Use a checkout containing the Phase 1 files. Run commands from the repository
root. You need Docker Engine with Compose, permission to use the local daemon,
and Python 3.14 for the documented local test environment. Initial image and
package downloads require internet access. No paid service or trial is required.
The host PostgreSQL service is not needed.

Before a first setup, check the Docker context, available ports, and existing
resources. Ports 8088 and 8089 must be available; do not reuse another stack's
`sdt-demo` resources.

```bash
docker context show
ss -ltn
docker ps -a --filter label=com.docker.compose.project=sdt-demo
docker volume ls --filter name=sdt-demo
docker network ls --filter name=sdt-demo
docker image ls sdt-demo-api
```

Use the intended local Docker daemon. Investigate any name collision before
starting. For an existing installation, use the resume commands below instead
of generating new credentials.

Generate `.env` once. This refuses to overwrite an existing file and does not
print its values. `.env.example` lists the required variables.

```bash
python - <<'PY'
import os
import secrets

fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write(f'POSTGRES_PASSWORD={secrets.token_hex(24)}\n')
    file.write(f'APP_DB_PASSWORD={secrets.token_hex(24)}\n')
print('Created .env without displaying its contents.')
PY
```

The `&&` operators stop this setup sequence if a command fails. Investigate the
failure before continuing; do not rerun initialization to hide a data problem.

```bash
git check-ignore .env &&
docker compose config --quiet &&
docker compose build api &&
docker compose up -d --wait --wait-timeout 120 db &&
docker compose run --rm init &&
docker compose up -d --wait --wait-timeout 120 api nginx &&
python tests/smoke.py
```

Initialization creates the fixed table, inserts missing fixture records, and
configures the reader account. It refuses conflicting fixture values instead
of overwriting them. Repeating it also reapplies grants and sets the reader
password; it is not a password-rotation workflow.

The normal smoke check expects exactly Notebook, Pencil, and Folder. It checks
all four endpoints directly and through NGINX. A pass is a point-in-time result,
not a continuous availability guarantee.

| Endpoint | Purpose |
|---|---|
| `GET /items` | Read at most 100 catalogue records ordered by ID |
| `GET /health/live` | Confirm the API can answer without consulting PostgreSQL |
| `GET /health/ready` | Check access to the catalogue table |
| `GET /version` | Return the image's `demo-v1` release metadata |

NGINX is at `http://127.0.0.1:8088`; the direct API is at
`http://127.0.0.1:8089`. PostgreSQL has no published host port.

To stop this stack while preserving data:

```bash
docker compose stop
```

To resume the existing installation using its locally available images and
unchanged configuration:

```bash
docker compose start --wait --wait-timeout 120 db api nginx &&
python tests/smoke.py
```

These resume commands start existing containers; they do not recreate missing
ones. Investigate missing containers or images before rebuilding. After toolkit
deployment, plain `docker compose up` can reapply the base Phase 1 image, bypassing
toolkit records. Use the toolkit for release changes; do not use resume as deployment.

Keep the existing `.env` and named volume. Do not reseed to conceal a failed
persistence check. Changing `POSTGRES_PASSWORD` in `.env` does not update an
administrator password already stored in the database.

## Local tests

The application dependencies are installed inside its Docker image. For local
unit tests, create a separate environment once:

```bash
python -m venv .venv
```

For a new or existing environment, activate it and install the development lock.
The sequence stops on a failure:

```bash
source .venv/bin/activate &&
python -m pip --require-virtualenv install -r requirements-dev.lock &&
python -m pip check &&
PYTHONPATH=demo python -W error -m unittest discover -s tests -p 'test_*.py' -v &&
PYTHONPATH=demo python -O -W error -m unittest discover -s tests -p 'test_*.py' -v
```

The suite includes demo, CLI, preflight, subprocess and journal tests. It uses
simulated database/Docker responses plus real temporary files and child processes.
It does not replace live smoke checks or Docker integration exercises. Historical
counts and current verification results are in the Phase 2 evidence document.

`demo/requirements.txt` records direct runtime dependencies;
`demo/requirements.lock` pins the observed runtime set used by Docker.
`requirements-dev.txt` describes the development inputs;
`requirements-dev.lock` pins the resolved development set.
These files pin versions without package hashes. Base images are pinned by
digest; dependency and image updates require deliberate review and retesting.

## Verified locally

- Normal responses through the API and NGINX, including database reads.
- Database outage responses and recovery without restarting the API.
- Denial of INSERT, UPDATE, and DELETE on the catalogue using the API account.
- Fixture persistence across database-container replacement without reseeding.
- Refusal to overwrite conflicting fixture data, followed by restoration.
- Locked-image rebuild, running-image identity, and all 16 runtime package pins.
- Phase 1 fresh development-lock installation with nine passing tests in both modes.
- Phase 2's 153 tests passed in both modes with no reported cleanup warnings.
- Verification-only left the API container unchanged; a wrong expected release
  failed while preserving the previous successful record.
- Stopped-API and changed-image replacement passed with database and NGINX
  container IDs unchanged; explicit redeployment returned the demo to v1.

These are local results, not CI results or a complete clean-machine installation
claim. Detailed evidence boundaries and remaining gaps are recorded in
[Known issues and limitations](docs/KNOWN-ISSUES.md).

## Current toolkit commands

Run from this checkout's root. Inspection supports the default local Docker
socket at `/var/run/docker.sock`; Desktop, rootless and remote contexts are not
supported by the toolkit. The demo setup above is still required before preflight.

```bash
python -m toolkit --help
python -m toolkit validate --image sdt-demo-api:phase1 --release demo-v1
python -m toolkit status
python -m toolkit preflight --image sdt-demo-api:phase1 --release demo-v1
```

Validation checks input shape only. Status reports local records and observed
container states, not application health. Preflight checks supported ownership,
resources and local image identity; it neither deploys nor verifies HTTP behavior.
An owned stopped API is permitted, but the database and proxy must be running.
`deploy` is now implemented. It acquires the lock, checks resources, records
pending intent and either verifies the matching running image or replaces only
the API. A matching stopped API still requires replacement.

Deployment uses a per-checkout lock and `.runtime/toolkit/`. A pending operation
blocks another deployment; read-only status remains available. Once initialized, a missing snapshot is refused if
its initialization marker remains. Never delete operation state to bypass a
refusal. Read-only commands do not create or upgrade journals.

## Deploy a local image

Build the intended image separately. The toolkit never pulls or builds it, seeds
the database, or requests dependency replacement. Candidates must preserve the
demo image user `10001:10001` and the existing API contract.

```bash
python -m toolkit deploy --image sdt-demo-api:phase1 --release demo-v1
```

The current running Phase 1 image normally takes the `verify-only` path. This
still records a real verification operation. When replacement is required, a
strict image-only override is written to `.runtime/toolkit/compose-image.json`.
The base Compose file and working image tag are not edited.

Success requires container state, liveness, expected image/release, direct
catalogue and proxy catalogue checks in one accepted attempt. The journal records
`action` and five check results. Failure returns nonzero; no rollback occurs.
After an uncertain command result, the tool attempts up to ten seconds of
read-only verification observations and retains pending intent even if they pass.
Do not delete that record to retry. Reconciliation remains Phase 3 work.

See [Phase 2 verification](docs/PHASE-2-VERIFICATION.md) for timing, exit codes,
configuration boundaries, and the distinction between tests and live acceptance.

## Reproduce Phase 2 acceptance

The manual driver is [scripts/phase2-acceptance.py](scripts/phase2-acceptance.py).
Its three stages were run successfully by the owner before the driver was added
to the repository unchanged. See the [reproduction instructions](docs/PHASE-2-VERIFICATION.md#reproduce-the-live-exercises)
for prerequisites, commands and expected effects. These exercises deliberately
replace the demo API; they are not part of automatic unit-test discovery.

## Next phases and boundaries

Phase 2 is ready for final PR review after the closure documentation is applied.
Phase 3 adds manual rollback and reconciliation; automatic recovery will require
opt-in and compatibility checks. Recovery and reconciliation are not implemented.

The baseline targets one local stack. It excludes Kubernetes, paid hosting,
AI classification, database rollback, high availability, and zero-downtime
guarantees. PostgreSQL persistence is not a backup.

- [Architecture](docs/ARCHITECTURE.md)
- [Decisions](docs/DECISIONS.md)
- [Known issues and limitations](docs/KNOWN-ISSUES.md)
- [Phase 2 contract and verification](docs/PHASE-2-VERIFICATION.md)

## License

[MIT](LICENSE).
