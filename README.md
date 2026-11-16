# Service Deployment Toolkit

A local project for checking containerized releases and recovering from failed
deployments. The deployment and recovery CLI is still planned. The working
foundation is a small FastAPI catalogue, PostgreSQL, and NGINX.

## Current status

Phase 1 implementation and local checks are complete; documentation and PR
review are in progress. There is no automated deployment or rollback command yet.

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
docker compose up -d --no-build --pull never --wait --wait-timeout 120 db api nginx &&
python tests/smoke.py
```

If an image is missing, investigate before rebuilding or pulling it. Resume is
not the procedure for deploying a changed application.

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

There are nine unit tests, run in two modes. They use simulated database or HTTP
behavior; they do not replace the live smoke check or manual integration exercises.

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
- Fresh development-lock installation with nine passing tests in both modes.

These are local results, not CI results or a complete clean-machine installation
claim. Detailed evidence boundaries and remaining gaps are recorded in
[Known issues and limitations](docs/KNOWN-ISSUES.md).

## Next phases and boundaries

Next comes explicit image selection, ownership checks, deployment locking,
operation records, and five deployment verification check types. Manual rollback
will be the default; automatic recovery will require opt-in and compatibility
checks. None of these toolkit operations is implemented yet.

The baseline targets one local stack. It excludes Kubernetes, paid hosting,
AI classification, database rollback, high availability, and zero-downtime
guarantees. PostgreSQL persistence is not a backup.

- [Architecture](docs/ARCHITECTURE.md)
- [Decisions](docs/DECISIONS.md)
- [Known issues and limitations](docs/KNOWN-ISSUES.md)

## License

[MIT](LICENSE).
