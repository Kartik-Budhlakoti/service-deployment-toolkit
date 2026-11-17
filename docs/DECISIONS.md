# Decisions

Status: Phase 1 merged. Phase 2 deployment is implemented at `fa8aaf1`, including
the corrective batch and Batch D fix 1. All 153 owner-side tests passed in both
modes, and the three planned live acceptance stages passed. Phase 2 PR closure
is in progress; this does not claim the branch has merged.

A recorded decision alone does not establish that its behavior is implemented
or verified. CLI validation, Docker inspection, and the operation journal/lock
components are implemented and integrated with the deployment command. Live
acceptance passed for the recorded scenarios; recovery remains future work.
Status reads records and observes Docker.

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
| D11 | Resolve deployed application images to immutable identifiers. | Avoids treating a movable tag as a reliable recovery target; Batch B resolves a local candidate to its immutable image ID. Batch D now uses and verifies that identity; the recorded live acceptance passed. |
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
an immutable image ID. Batch D now deploys that ID and checks actual image/release
identity; the recorded live acceptance passed.

## Phase 2 decisions and current implementation status

The following implementation choices were initially supplied by the assistant.
They are recorded explicitly here without retroactively attributing individual
selection to the user. See the inventory for alternatives and detailed costs.

| ID | Choice | Reason, consequence, and status |
|---|---|---|
| D21 | Standard-library argparse with `python -m toolkit`. | Small dependency footprint. Implemented in Batch A. |
| D22 | Locally available candidate image and separate expected release input. | Keeps image acquisition outside deployment. Resolution and release verification implemented; the recorded live deployment acceptance passed. |
| D23 | Fixed demo configuration and default local Docker socket. | Bounds supported environments. Desktop/rootless contexts remain outside current support. |
| D24 | Verification/request/retry/command defaults of 60/3/1/60 seconds. | Initial policy values, not measured performance requirements. Input validation, command timeouts and shared verification deadline implemented; cleanup uses a separate allowance. |
| D25 | Targeted ownership checks before mutation. | Refuses unexpected checkout labels, resources and sharing. Checks repeat under the deployment lock; external Docker commands remain outside that lock. |
| D26 | Bounded subprocess capture with raw errors withheld. | Limits output and avoids printing configuration values. Generic failures provide limited diagnostic detail. Implemented. |
| D27 | One nonblocking Linux file lock per checkout. | Coordinates participating toolkit processes in that checkout. Cross-checkout/global coordination is outside this implementation. Implemented and tested with separate processes. |
| D28 | JSON snapshot with latest operation and last success, plus archived completed records. | Inspectable local history with custom validation and filesystem handling. Implemented and tested. |
| D29 | Persist pending intent before mutation and block unfinished/invalid state. | Preserves uncertainty after interruption. Deployment integration implemented; reconciliation remains Phase 3 work. |
| D30 | Temporary-file replacement and filesystem synchronization for records. | Reduces partial-write exposure. Write-failure tests passed. Sudden power-loss durability remains untested. |
| D31 | Read-only status remains available when operation state is uncertain. | Supports diagnosis. Uncertainty exits 6 even if Docker observation also fails. Implemented. |
| D32 | Verify a matching image already running, without unnecessary replacement. | User explicitly selected and reaffirmed. Full verification precedes success recording. Implemented in Batch D; the recorded live acceptance passed. |
| D33 | Allow an explicit deployment to replace a stopped, owned API when dependencies and recorded state permit it. | User explicitly selected and reaffirmed after discussing the startup-failure scenario. Preflight now permits an owned API in the exited state while retaining dependency and ownership checks. Deployment integration is implemented; the recorded live acceptance passed. |

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
  by automated tests. Actual replacement is now implemented by Batch D; the recorded live acceptance passed.

## Remaining implementation decisions

Phase 2 acceptance is recorded in PHASE-2-VERIFICATION.md. D32/D33, the wrong
expected-release path, a separately built candidate and dependency-container
preservation passed their live exercises. The remaining handoff is review and
merge of the Phase 2 PR; no further deployment feature is added by closure.

Batch D implements shared deadlines, bounded probes, five result groups, exit-code
handling, generated-override ownership, selected configuration consistency checks
and action recording. Automated tests do not replace the live acceptance above.

The basic image identity, lock and JSON formats are implemented. Their integration
passed the recorded live scenarios; this does not verify every failure path.
Recording every attempted operation remains a broader baseline goal: current read-only commands do not
persist operation history. Deployment records start after successful preflight;
refusals before begin are reported only in the terminal.

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
| D35 | After a deployment timeout, preserve uncertainty and attempt bounded read-only observations. | User selected. Do not retry, roll back or mark success solely from a timeout or a later healthy snapshot. Batch D implements observation reporting; reconciliation belongs to Phase 3. |
| D36 | Isolate local command process groups and bound cleanup. | Assistant implementation detail supporting D35. Kills ordinary descendants without claiming cancellation of daemon work or escaped process groups. Implemented for the inspection runner. |

CLI unit tests supply explicit state instead of reading the operator's journal.
This fixes test isolation without changing the CLI's exit-code policy. Decision
inventory updates remain external study material; no selected-trade-offs file is
added to this repository.

## Batch D implementation decisions

These entries extend the A–C choices with Batch D implementation details. D32 and D33
are implemented, tested with a simulated daemon, and exercised successfully on
the owner's Docker stack. D35 is implemented for unconfirmed command outcomes;
reconciliation remains Phase 3. The initial timing defaults remain unchanged.

| ID | Choice | Reason and consequence |
|---|---|---|
| D37 | Retained image-only JSON Compose override at a fixed local path. | Selects an immutable API image without editing the base file. Exact ownership-label validation supports subsequent deployments. Plain Compose up can still reapply the base image. |
| D38 | Child-process HTTP probes with a shared monotonic verification deadline. | Bounds slow headers/bodies beyond a socket inactivity timeout. Adds local process startup overhead and a separate cleanup allowance. |
| D39 | Ten-second post-command-error observation budget. | Gives bounded evidence while preserving pending intent. It is separate from normal verification time and does not authorize retry or rollback. |
| D40 | Version-2 deployment snapshots include action and five check results. | Distinguishes verify-only from replacement. Version-1 records remain readable; version-2 snapshots require their marker. |
| D41 | Fingerprint three configuration files in memory and restrict supported API settings. | Detects observed file changes without storing secret hashes. This is not full runtime drift detection or Phase 3 compatibility validation. |

These implementation details were selected by the assistant within the approved
batch scope. Candidate images retain user 10001:10001. No new paid service,
infrastructure platform, rollback mode or application feature is introduced.

## Batch D corrections and Phase 2 closure

- The replacement guard accepts absent or null `command` and `entrypoint` fields
  because they preserve image defaults. Non-null values, including empty strings
  and lists, remain refused. This corrects a false refusal, not a new startup mode.
- HTTPError response objects are explicitly closed. The initial 149-test owner
  run emitted cleanup warnings despite reporting OK; the corrected 153-test run
  passed without those warnings. Defects are not accepted as trade-offs.
- Batch E updates current-status wording and publishes the unchanged manual
  acceptance driver under scripts/ so reviewers can reproduce the exercises.
  It changes no deployment behavior and adds no dependency. Study documents
  remain outside the repository; a selected-trade-offs document is deferred
  until the end of the project, if the owner wants it.
