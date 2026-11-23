# Decisions

Phase 2 merged at `e960f68` after the owner's 153 tests and three live deployment
exercises. Phase 3 Batch B implements the manual recovery choices below on
the recovery branch. The owner's 180 tests passed in both modes and its planned
live baseline and flagged manual rollback exercise passed on 22 November 2026.
The combined recovery batch subsequently passed 214 tests in both modes and
the dedicated live reconciliation and automatic recovery exercises.
[Phase 3 live results](PHASE-3-RECOVERY.md#combined-live-results)

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
| D29 | Persist pending intent before mutation and block unfinished/invalid state. | Preserves uncertainty after interruption. Deployment uses this guard. Phase 3 adds explicit closure of a pending operation. |
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
preservation passed their live exercises. The Phase 2 PR merged at `e960f68`.

Batch D implements shared deadlines, bounded probes, five result groups, exit-code
handling, generated-override ownership, selected configuration consistency checks
and action recording. Automated tests do not replace the live acceptance above.

The basic image identity, lock and JSON formats are implemented. Their integration
passed the recorded live scenarios; this does not verify every failure path.
Recording every attempted operation remains a broader baseline goal: current read-only commands do not
persist operation history. Deployment records start after successful preflight;
refusals before begin are reported only in the terminal.

Phase 3 implements compatibility checks, a schema declaration, reconciliation
and a strict automatic recovery policy. The decisions and acceptance status
are recorded below and in [the Phase 3 contract](PHASE-3-RECOVERY.md).

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
| D35 | After a deployment timeout, preserve uncertainty and attempt bounded read-only observations. | User selected. Do not retry, roll back or mark success solely from a timeout or a later healthy snapshot. Batch D implements observation reporting; Phase 3 implements explicit pending closure. |
| D36 | Isolate local command process groups and bound cleanup. | Assistant implementation detail supporting D35. Kills ordinary descendants without claiming cancellation of daemon work or escaped process groups. Implemented for the inspection runner. |

CLI unit tests supply explicit state instead of reading the operator's journal.
This fixes test isolation without changing the CLI's exit-code policy. Decision
inventory updates remain external study material; no selected-trade-offs file is
added to this repository.

## Batch D implementation decisions

These entries extend the A–C choices with Batch D implementation details. D32 and D33
are implemented, tested with a simulated daemon, and exercised successfully on
the owner's Docker stack. D35 is implemented for unconfirmed command outcomes;
the Phase 3 reconciliation command handles validated pending records. The initial timing defaults still apply.

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

## Phase 3 Batch A — recovery target and eligibility

Phase 2 merged at `e960f68`. These two owner-selected rules define the Phase 3 design. Batch B implements the manual path. The owner's live exercise verified target
selection, the comment-only exception and real environment-change refusal.

| ID | Decision | Alternative and cost |
|---|---|---|
| D42 | Manual rollback selects a verified successful operation by full ID and repeats eligibility checks before mutation. | Implicitly selecting the preceding success is quicker, but repeated verification and deployment can make the intended target ambiguous. Showing release, time and image alongside the operation ID helps the operator choose. |
| D43 | Manual rollback may explicitly accept changed base Compose file bytes only when the entire supported resolved base model and all independent compatibility evidence still match. Automatic recovery stays strict. | Strict-only refusal is simpler but blocks comment edits. A general force flag could accept a changed credential or dependency. The narrow exception adds evidence collection, comparison and tests. Legacy records require fresh verification before a new eligible baseline can exist. |

See the [Phase 3 recovery contract](PHASE-3-RECOVERY.md) for the decision table, secret handling and required evidence.

## Phase 3 Batch B implementation choices

| Choice | Reason | Cost |
|---|---|---|
| Register an already running release through an explicit `baseline` command and `--schema catalogue-v1`. | The operator identifies the trusted image and its intended database contract. The toolkit verifies it and inspects the actual schema. | An ordinary deployment or an older success needs a fresh verification before it can serve as a recovery target. |
| Keep a signed compatibility snapshot in the successful operation record. | Pending intent, exception use and final result remain associated with one operation. | Loss of the local key invalidates its comparisons. |
| Accept the shipped Compose source plus a small set of formatting changes. | This bounds which external inputs can affect recovery while using the installed Compose renderer to check the complete model. | Some equivalent YAML rewrites require review and a toolkit change. |

## Phase 3 combined batch decisions

D05, D06, D35, D42 and D43 establish the policy. The implementation choices
below define the command interface and the evidence required to act.

| ID | Selected behavior | Reason and cost |
|---|---|---|
| D44 | Preview by full pending operation ID. Require explicit closure as `closed-unknown` under the lock. | A present-day observation cannot establish whether an interrupted operation completed. The operator must confirm that Docker work has settled. |
| D45 | Repair a generated override when it points at the image named in a recorded pending replacement and the observed API belongs to this checkout. | A process can exit after saving the override. The repair changes a local file and requires stable resource observations. Unexplained mismatches and corrupt history require investigation. |
| D46 | Require both `--auto-recover` and `--schema catalogue-v1`. Use the last recorded success only, reverify it live and require a distinct candidate image. | A recorded success may be stale. One eligible running release makes the target predictable. Older eligible entries remain available through explicit manual selection. |
| D47 | Record the confirmed candidate failure before one separately journaled recovery attempt under the same lock. Require the same observed container ID and start time. | The deployment failure survives recovery. If the process stops between the two records, an operator must decide what to do next. |
| D48 | Repeat strict compatibility checks after rendering the stored plan, then confirm the current API before submitting the replacement. Save evidence after verified success. | Runtime settings and the selected release must still agree. Additional inspection can refuse a target and adds time before deployment. |
| D49 | Keep exit code `1` for a failed requested deployment even when automatic recovery succeeds. | A caller can detect the failed release. Operators can read the recovery record for the restored service outcome. |
| D50 | Use version 4 records for explicit unknown closure and automatic deployment/recovery links. | Old records remain readable in the new toolkit. Older readers can refuse a newer snapshot. Recovery history checks the links between automatic operations. |

## Phase 4 diagnostic collection

| ID | Decision | Reason and cost |
|---|---|---|
| D51 | Offer one read-only, on-demand command scoped to the owned local demo. | An operator can inspect a healthy or degraded stack using the same four checks. Missing or foreign resources can prevent inspection. |
| D52 | Check database name resolution and TCP reachability independently from the API container. | Testing the inspected database address separately keeps a name failure distinguishable from a refused connection. The check covers the demo's IPv4 network. |
| D53 | Bound collection time and print only selected outcomes and elapsed times. | Raw errors can include configuration values. A generic worker failure sometimes leaves the cause unknown. |

### Operation reports

| ID | Choice | Reason and cost |
|---|---|---|
| D54 | Retain the first failed verification attempt and the last observed attempt with the journal outcome. | The failed candidate can disappear during recovery. Reusing its verification requests adds no probe sweep. Intermediate attempts and unobserved causes remain unknown. |
| D55 | Export an incident report after the recovery decision. Put the failed candidate and its linked automatic attempt in one JSON file. | A report write failure is visible to the operator and preserves the deployment exit code. A process killed before export may require manual regeneration. |
| D56 | Export selected fields from validated local history. Allow an explicit export by full operation ID, including a success. | Export works offline and avoids raw responses, operator release text and signed compatibility data. Older operations contain fewer details. A concurrent operation can delay export. |

| ID | Acceptance choice | Reason and cost |
|---|---|---|
| D57 | Exercise PostgreSQL and NGINX separately, by stopping and starting the existing owned container under the checkout lock. | The remaining routes reveal which service is still usable. The local demo is briefly degraded, and a hard interruption can require a manual start. |
| D58 | Reuse the Phase 3 failed-start fixture and check a fresh linked report before re-exporting it. | This exercises the real deployment entry point and catches a missing automatic export. The stage takes longer than reading an old incident and retains a local candidate image. |

## Release verification

| ID | Decision | Reason and cost |
|---|---|---|
| D59 | Run the Python suite in normal and optimized modes on Ubuntu 24.04 x64 with Python 3.14.10. Install the development lock in a fresh virtual environment. | Matches the locally tested Python version. Optimized mode catches checks that disappear with assertions. One host configuration keeps the result interpretable and leaves other platforms untested. |
| D60 | Run the same Python job on pull requests to `main` and pushes to `main`. Give the job read access to repository contents and pin its two actions by commit. | Reviewers can inspect the PR result and the result for the merged commit. Pinned actions need deliberate updates. A real Docker installation and recovery exercise require separate evidence. |
