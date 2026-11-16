# Decisions

Status: Phase 0 decisions retained; Phase 1 implementation and local checks
complete, with documentation and PR review in progress.

A recorded decision alone does not establish that its behavior is implemented
or verified. Deployment, recovery, locking, and reporting decisions below remain
requirements for later phases.

## Baseline decisions

| ID | Decision | Reason and consequence |
|---|---|---|
| D01 | Keep the toolkit and demonstration in one new repository. | Keeps implementation, fixtures, and tests together; the baseline supports one known workload. |
| D02 | Leave the original diet and medical repositories and their Docker resources unchanged. | Preserves earlier work and avoids unintended deployment changes. |
| D03 | Use a minimal read-only catalogue with PostgreSQL. | Provides a meaningful dependency check without nutrition logic or account management. |
| D04 | Run locally using Docker Engine and Compose. | Requires no paid hosting, expiring trial, or additional VM; minimum resource requirements are not measured. |
| D05 | Use manual rollback by default. | A failed check does not establish that reverting an image is the correct remedy; manual mode may leave service unavailable. |
| D06 | Make automatic recovery an explicit opt-in. | Limits recovery to eligible image-only changes under unchanged runtime configuration, schema, and dependency arrangement; compatibility is not universally provable. |
| D07 | Use deterministic checks and reporting rules. | Keeps behavior explainable and avoids an AI dependency. |
| D08 | Attempt a small record for every operation. | Provides local operation history when recording succeeds; recording failures must be disclosed. |
| D09 | Keep the demonstration schema fixed after Phase 1. | Avoids introducing migration and downgrade behavior into application rollback. |
| D10 | Use feature branches and pull requests after bootstrap. | Makes changes reviewable; solo PRs do not imply independent review. |
| D11 | Resolve deployed application images to immutable identifiers. | Avoids treating a movable tag as a reliable recovery target; this toolkit mechanism is not implemented yet. |
| D12 | Keep database backup and restore outside the baseline. | A persistent volume supports container replacement but does not provide disaster recovery. |

## Demo workload selection

The initial proposal considered reusing the existing diet-recommendation API.
The Phase 0 baseline instead selected a new, minimal read-only catalogue backed
by PostgreSQL. The implementation does not reuse that project's code, database
contents, or Docker images.

The catalogue supplies the database dependency needed for deployment and recovery
exercises without importing recommendation logic or unrelated application features.
The trade-off is that the baseline demonstrates a purpose-built workload, not
integration with the existing diet API. Adding that integration would require a
separate scope decision. No measured time-saving claim is made for this choice.

## Phase 1 implementation decisions

| ID | Selected option and alternative | Reason and consequence |
|---|---|---|
| D13 | Python 3.14, tested locally as 3.14.10, rather than changing Python versions during this phase. | Matches the existing host environment; compatibility outside the tested Linux environment remains unverified. |
| D14 | `sdt-demo`, loopback ports 8088/8089, and a dedicated named volume rather than existing project resources. | Separates the demo and supports direct/proxy checks; users must still check collisions because toolkit ownership validation does not exist yet. |
| D15 | Explicit initialization and fixture verification rather than automatic seeding on API startup. | Keeps data changes visible and separates application startup from database setup; setup requires an extra command. |
| D16 | A separate catalogue reader account and administrative initializer rather than giving the API administrator credentials. | Limits catalogue writes through the API account; credentials remain local environment values, not a secret-management service. |
| D17 | Liveness-based container health plus separate database-readiness and catalogue checks rather than one combined health signal. | Makes process availability distinguishable from dependency failure; a healthy API container can still be unable to serve catalogue reads. |
| D18 | Exact package versions and base-image digests rather than mutable build inputs alone. | Reduces version drift; updates need deliberate review. Version locks have no package hashes and do not guarantee identical builds across platforms. |
| D19 | `httpx2` for the test client rather than retaining the deprecated `httpx` path. | Removes the observed test-client deprecation warning; this dependency belongs to development, not the runtime image. |
| D20 | Explicit smoke-check comparisons rather than `assert` statements containing requests. | Prevents optimized Python from skipping requests and reporting false success; regression tests exercise both execution modes. |

The table and reader setup use a fixed `public.items(id, name)` schema and three
synthetic fixtures. Seeding inserts missing fixture IDs without replacing
existing values, then checks those values. Repeated initialization also updates
the reader password and reapplies grants; it is not a general reconciliation or
credential-rotation system.

`demo/requirements.txt` records direct runtime inputs. The Dockerfile installs
`demo/requirements.lock`. Development inputs are in `requirements-dev.txt`, and
repeatable local test setup uses `requirements-dev.lock`. When dependencies change,
update the related inputs and locks together, review their differences, and
repeat the affected build and tests. Do not install test-client packages into
the runtime image simply to run host-side unit tests.

Pinning the Python, PostgreSQL, and NGINX base images does not fulfill D11 by
itself. The current application tag `sdt-demo-api:phase1` is mutable; Phase 2
must implement explicit immutable application-release selection.

## Remaining implementation decisions

Before Phase 2 is complete:

- Image identity and release metadata format beyond the demo's `demo-v1` string.
- Verification deadlines and retry behavior.
- Deployment lock and operation-state format.
- Exit-code mapping and initial report fields.
- Resource ownership checks.

Before automatic recovery is enabled in Phase 3:

- Configuration-change detection, including secret-handling limits.
- Supported compatibility declarations and eligibility checks.
- Interrupted-operation reconciliation procedure.
- Behavior when the previous image or required state is unavailable.

Details must be resolved before the dependent behavior is accepted. Local
Phase 1 checks do not establish that the later toolkit design is verified.

## Scope-change rule

A new baseline feature must fix an acceptance failure or replace work of similar
effort without weakening existing acceptance criteria. Other additions are
deferred until after the first release.

For a changed decision, record:

- The alternatives considered.
- The selected option and reason.
- The consequences and limitations.
- The affected acceptance criteria.
- Any change to the estimated effort.
