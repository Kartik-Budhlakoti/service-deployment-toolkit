# Decisions

Status: Phase 1 merged. Phase 2 Batches A–C and the stopped-API revision are
committed through `7397feb`. The corrective batch is based on that commit; its
local verification is recorded separately. Batch D is pending.

A recorded decision alone does not establish that its behavior is implemented
or verified. CLI validation, Docker inspection, and the operation journal/lock
components are implemented. Integration with live deployment and recovery remains
pending. Status reads local operation records and observes Docker.

A separate study document contains the detailed decision inventory and is maintained outside this repository.
Local Phase 2 evidence is in [PHASE-2-VERIFICATION.md](PHASE-2-VERIFICATION.md).
The inventory distinguishes assistant implementation choices from explicit user
selections. Early individual attribution is incomplete.

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
| D11 | Resolve deployed application images to immutable identifiers. | Avoids treating a movable tag as a reliable recovery target; Batch B resolves a local candidate to its immutable image ID. Batch D must use and verify that identity during deployment. |
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
| D14 | `sdt-demo`, loopback ports 8088/8089, and a dedicated named volume rather than existing project resources. | Separates the demo and supports direct/proxy checks; Batch B now checks supported resource ownership, ports, and mounts. These checks are a snapshot and must be repeated in the deployment workflow. |
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
itself. The application tag `sdt-demo-api:phase1` is mutable. Batch B resolves it to
an immutable image ID. Deploying that ID and checking the actual running image
remain Batch D requirements.

## Phase 2 decisions and implementation status

The following implementation choices were initially supplied by the assistant.
They are recorded explicitly here without retroactively attributing individual
selection to the user. See the inventory for alternatives and detailed costs.

| ID | Choice | Reason, consequence, and status |
|---|---|---|
| D21 | Standard-library argparse with `python -m toolkit`. | Small dependency footprint. Implemented in Batch A. |
| D22 | Locally available candidate image and separate expected release input. | Keeps image acquisition outside deployment. Resolution implemented, release verification pending. |
| D23 | Fixed demo configuration and default local Docker socket. | Bounds supported environments. Desktop/rootless contexts remain outside current support. |
| D24 | Verification/request/retry/command defaults of 60/3/1/60 seconds. | Initial policy values, not measured performance requirements. Input validation and command timeouts implemented. Shared verification deadline pending. |
| D25 | Targeted ownership checks before mutation. | Refuses unexpected checkout labels, resources and sharing. Read-only checks implemented. Rechecking under the mutation lock is pending. |
| D26 | Bounded subprocess capture with raw errors withheld. | Limits output and avoids printing configuration values. Generic failures provide limited diagnostic detail. Implemented. |
| D27 | One nonblocking Linux file lock per checkout. | Coordinates participating toolkit processes in that checkout. Cross-checkout/global coordination is outside this implementation. Implemented and tested with separate processes. |
| D28 | JSON snapshot with latest operation and last success, plus archived completed records. | Inspectable local history with custom validation and filesystem handling. Implemented and tested. |
| D29 | Persist pending intent before mutation and block unfinished/invalid state. | Preserves uncertainty after interruption. Journal primitive implemented. Deployment integration and reconciliation remain pending. |
| D30 | Temporary-file replacement and filesystem synchronization for records. | Reduces partial-write exposure. Write-failure tests passed. Sudden power-loss durability remains untested. |
| D31 | Read-only status remains available when operation state is uncertain. | Supports diagnosis. Uncertainty exits 6 even if Docker observation also fails. Implemented. |
| D32 | Verify a matching image already running, without unnecessary replacement. | User explicitly selected and reaffirmed. Full verification must precede success recording. Batch D implementation pending. |
| D33 | Allow an explicit deployment to replace a stopped, owned API when dependencies and recorded state permit it. | User explicitly selected and reaffirmed after discussing the startup-failure scenario. Preflight now permits an owned API in the exited state while retaining dependency and ownership checks. Deployment integration remains pending. |

D32 applies to an API that is running. A stopped API still needs startup or
replacement even when the selected image ID matches. D33 does not permit
bypassing pending-operation or ownership checks.

## Decision changes and corrections

- Demo selection changed from proposed diet-API reuse to a new catalogue (D03).
- Request-bearing assertions were corrected because optimized Python removed
  the checks (D20). This is a defect correction, not a reliability trade-off.
- Initialization error wording was corrected to acknowledge uncertain commits.
- Batch B configuration inspection was corrected to include profiled services.
  Live preflight subsequently passed. This is recorded as B01 in the evidence file.
- D33 revises the earlier implementation choice requiring the API to be running
  before a new deployment. The preflight revision is implemented and covered
  by automated tests. Actual replacement through the deployment command
  remains Batch D work.

## Remaining implementation decisions

Before Phase 2 is complete:

- Enforce and test one verification deadline, bounded retries and response limits.
- Define the five check results and concise deployment report fields.
- Integrate exit codes for lock contention, uncertain mutation, recording failure
  and interruption through the actual deployment command.
- Extend ownership checks for the toolkit-generated Compose override.
- Specify configuration consistency across image selection, preflight and replacement.
- Record the action performed so verification-only success is distinguishable
  from a container replacement.
- Demonstrate the two user-selected D32/D33 behaviors and failure paths.

The basic image identity, lock and JSON formats are implemented. Their full
integration must still pass acceptance checks. Recording every attempted
operation remains a broader baseline goal: current read-only commands do not
persist operation history, and deployment-attempt reporting is pending.

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

## Review cadence

At the start of each batch, present meaningful behavior and scope choices with
scenarios, recommendations, alternatives and costs. At the end, update the
inventory with the implemented behavior and evidence. Consider a separate selected-trade-offs document at the end of the
project, if the owner considers it useful. Preserve reasons for changed decisions and mark
superseded behavior explicitly. Routine code details can be chosen by the
assistant, with consequential assumptions recorded for review.

## Corrective batch decisions

| ID | Choice | Reason and consequence |
|---|---|---|
| D34 | Persist an initialization marker before the first pending record. | User selected. A marker without a snapshot blocks mutation, including interrupted initialization. Valid legacy snapshots are upgraded before their next operation; complete deletion is not detectable. Implemented in this corrective batch. |
| D35 | After a deployment timeout, preserve uncertainty and attempt bounded read-only observations. | User selected. Do not retry, roll back or mark success solely from a timeout or a later healthy snapshot. Reporting integration belongs to Batch D; reconciliation belongs to Phase 3. |
| D36 | Isolate local command process groups and bound cleanup. | Assistant implementation detail supporting D35. Kills ordinary descendants without claiming cancellation of daemon work or escaped process groups. Implemented for the inspection runner. |

CLI unit tests supply explicit state instead of reading the operator's journal.
This fixes test isolation without changing the CLI's exit-code policy. Decision
inventory updates remain external study material; no selected-trade-offs file is
added to this repository.
