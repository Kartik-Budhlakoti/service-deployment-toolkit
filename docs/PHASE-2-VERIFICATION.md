# Phase 2 contract and verification

Current status: A–C and the stopped-API revision are implemented. The corrective
batch strengthens journal and subprocess handling. Live deployment is still
unavailable; Batch D and Phase 3 reconciliation remain pending. Earlier sections
are historical batch records; later corrections explicitly supersede them.

## Batch A: command interface (historical acceptance record)

Batch A implements argument parsing and input validation only. It does not
contact Docker, inspect the filesystem for deployment configuration, read .env,
write operation records, replace containers, or implement rollback. Python may
create its ordinary ignored bytecode cache. No third-party dependency is added.

Run commands from the repository root with the existing development environment.

| Command | Batch A behavior |
|---|---|
| `python -m toolkit --help` | Prints command help; exit 0. |
| `python -m toolkit validate --image sdt-demo-api:phase1 --release demo-v1` | Checks input shape and timeout relationships; exit 0 for accepted input. |
| `python -m toolkit status` | Reports that inspection is not implemented; exit 3. |
| `python -m toolkit deploy --image sdt-demo-api:phase1 --release demo-v1` | Validates input, then reports deployment is not implemented; exit 3. |

Input validation is not a deployment preflight. An accepted image string may
still be rejected by Docker or refer to a missing image. Validation restricts
characters and requires an explicit tag, SHA-256 digest, or complete local
SHA-256 image ID; it does not implement Docker's complete reference grammar.
Short IDs and implicit latest tags are intentionally unsupported. The expected
release is supplied separately, using 1–64 ASCII letters, digits, dots,
underscores or hyphens, starting with a letter or digit. It is a value to check
against the application, not proof of compatibility or a trusted identity.

## Selected implementation direction

Use standard-library argparse and `python -m toolkit`, rather than adding a CLI
framework or publishing a pip package at this stage. Keep the existing demo
project, service and addresses fixed. Do not add general-purpose stack support.

The selected image must already exist locally. Later batches will resolve its
immutable local image ID before deployment and verify the running container's
image ID afterward. No implicit image pull, build, database initialization or
dependency replacement is planned for the deployment command.

### Timing rules

| Option | Default | Accepted integer seconds |
|---|---:|---:|
| `--verification-timeout` | 60 | 1–600 |
| `--request-timeout` | 3 | 1–30 |
| `--retry-interval` | 1 | 1–30 |
| `--command-timeout` | 60 | 1–300 |

Request timeout must not exceed verification timeout; retry interval must be
smaller than verification timeout. Defaults are initial policy choices, not
measured startup requirements. Batch A validates these values but runs no timer.

Batch D must enforce one monotonic verification deadline shared by all retries,
cap work and sleeps to the remaining budget, and bound response bodies. A socket
timeout alone is not proof of an overall wall-clock limit. Command timeouts are
separate; verification timeout is not the total deployment duration. Timing out
the local Docker command does not prove the Docker daemon stopped its work.

### Exit-code contract

| Code | Meaning |
|---|---|
| 0 | Requested action completed successfully; validation success only validates inputs. |
| 1 | Deployment verification failed. |
| 2 | Invalid command or input. |
| 3 | Requested command is not implemented in this build. |
| 4 | Preflight refused deployment before replacement. |
| 5 | Another toolkit mutation holds the lock. |
| 6 | State or mutation outcome is uncertain; inspection is required. |
| 7 | Required operation recording failed. |
| 130 | Operation was interrupted. |

Only 0, 2 and 3 are implemented outcomes in Batch A. Other values reserve a
contract for later batches; declaring them does not implement their handling.
If several failures occur later, report each known outcome, select the most
actionable exit code, and never hide a recording failure behind a success code.
Exact precedence and interruption reporting will be specified with Batch C.

### State and ownership boundaries

Future state belongs under `.runtime/toolkit`, separate from Phase 1 evidence.
Before mutation, Batch B must check local Docker access, Compose configuration,
resource ownership and candidate-image availability. Batch C must acquire the
mutation lock and persist the operation intent before replacement. Missing
state on first use must be distinguished from unreadable or corrupt state.
Incomplete operations must block new mutations while permitting inspection.

Batch D will replace only the API, using a generated Compose override. Failure
must not overwrite the previous recorded successful release. Deployment failure
does not trigger automatic recovery in Phase 2. Manual/automatic rollback and
interruption reconciliation remain Phase 3 work; detailed networking diagnosis
remains Phase 4 work. These boundaries preserve the merged architecture scope.

## Batch A acceptance commands

```bash
python -W error -m unittest discover -s tests -p test_cli.py -v
python -O -W error -m unittest discover -s tests -p test_cli.py -v
```

There are 16 test methods, some containing multiple input cases. Coverage includes
valid input, invalid/missing arguments, abbreviated flags, image and release
boundaries, non-finite/non-integer timeout input, inconsistent deadlines,
unavailable commands, subprocess refusal, and the real module entry point from
an empty directory. Tests do not establish Docker integration or deployment safety.

Local Batch A verification passed on the project owner's Python 3.14.10
environment: all 25 tests passed normally and under optimization with warnings
treated as errors. Manual checks confirmed validation exit 0 and the then
unimplemented deployment/status commands returning exit 3.
Append later batch evidence here; do not mark planned checks as completed.


## Batch B: read-only inspection (historical acceptance record)

Batch B adds `preflight` and implements container observation through `status`.
The historical Batch A status exit code above no longer describes this build.
`validate` still checks inputs only. `deploy` still returns 3 without contacting
Docker. No deployment, image pull/build, initialization, cleanup, rollback,
operation-state writing or HTTP check is implemented by Batch B.

| Command | Batch B behavior |
|---|---|
| `python -m toolkit status` | Lists observed project service states and image IDs. Exit 0 means inspection completed, not that the application is healthy. An empty project is explicitly reported. |
| `python -m toolkit preflight --image sdt-demo-api:phase1 --release demo-v1` | Checks the current demo resources and resolves the local candidate image. Exit 0 means this read-only snapshot passed. |
| `python -m toolkit deploy --image sdt-demo-api:phase1 --release demo-v1` | Remains unavailable; exit 3. |

Inspection refusal or Docker failure returns 4. Invalid command/input returns 2.
At Batch B, status did not require valid Compose configuration, an .env file, or
operation state; it can report stopped containers. It performs no ownership or
HTTP acceptance check. An unknown service/metadata shape causes refusal rather
than an invented result.

### Scope and checks

The supported endpoint is the user's existing default Docker context at
`unix:///var/run/docker.sock`, serving Linux containers. Alternate contexts,
remote endpoints and relevant Docker/Compose environment overrides are refused.
This deliberately excludes Docker Desktop and rootless socket paths for now.
Each daemon command explicitly selects the default context. The tool does not
change the user's selected context.

Preflight requires an already initialized, running demo from this checkout:

- Explicit root compose.yaml, .env, project name and resolved Compose settings.
- Exactly the supported api, db, nginx and init service definitions.
- Expected loopback publications, declared mounts, network and named volume.
- A locally available candidate with a full immutable image ID, matching Linux
  architecture, and no image-declared volumes. It is not started for inspection.
- Exactly three project containers: one each for api, db and nginx. Labels must
  identify this project, this checkout, the original compose.yaml and normal
  service containers. Leftover initializer containers or duplicates cause refusal.
- Running containers, an explicitly healthy database, expected actual ports,
  mounts and network attachments. API health and catalogue behavior are not
  inferred from these checks.
- Running database and proxy image IDs matching their configured local images.
- A local named database volume with expected Compose labels and no other
  containers referencing it, including stopped containers.
- A bridge network with expected Compose labels and exactly the three expected
  container attachments.

Compose labels identify the expected resources but are not cryptographic proof
of ownership. Docker administrators can alter resources. Trusted local operators,
configuration and images remain assumptions. These are targeted checks, not a
complete comparison of every Compose setting or container privilege. Candidate
entrypoint behavior, credentials, schema compatibility, release contents and
application correctness are not verified here.

Inspection uses Docker's resolved Compose JSON and inspect metadata internally.
These can contain credentials; the tool does not print or persist raw results.
Output is limited to fixed descriptions and selected service/state/image-ID
fields. Errors withhold raw Docker stderr and command output. No secret scanner
or arbitrary-log redactor is claimed.

Each Docker subprocess has the configured command timeout (60 seconds for
status), and a combined stdout/stderr limit of 1 MiB. The limit is enforced while
reading. The deadline applies to each subprocess, not the whole preflight.
No retries are implemented in inspection. A changing/disappearing resource may
cause refusal; the user can inspect and retry.

### Required follow-up before deployment

A successful preflight is a snapshot, not authorization to mutate later using
stale observations. Batch C supplies the shared mutation lock and state checks;
Batch D must repeat the applicable checks while holding that lock immediately
before replacement. External Docker commands can still race with toolkit work.

The first deployment record must not treat the current Phase 1 image as a
previous toolkit-verified successful release merely because preflight passed.
A failed first toolkit deployment has no recorded recovery target.

Current checkout-label checks accept only the original compose.yaml. Batch D
must deliberately extend and test that rule for its generated override so that
a later deployment accepts toolkit-owned containers without accepting arbitrary
overrides. Preflight currently requires running services; recovery from a stopped
API is not implemented by this inspection batch. These are integration tasks,
not reasons to weaken the ownership checks now.

### Verification and evidence

The suite now contains 55 test methods: the original 25, two additional CLI
methods, 19 preflight methods and nine Docker runner methods. Some methods
exercise multiple input cases. The status tests were updated for its implemented
read-only behavior. This count is coverage bookkeeping, not a reliability score.

The new tests cover missing images, platform mismatch, image volumes, malformed
metadata, foreign checkout labels, duplicate/missing services, stopped containers,
unhealthy database, public ports, unexpected mounts, shared resources, dependency
image drift, missing Docker, command timeout, malformed JSON, bounded output,
withheld raw errors and local-context restrictions. Docker integration is modeled
with fixtures. Runner tests execute a temporary fake Docker executable to test
real subprocess behavior without contacting a daemon.

All 55 tests passed normally and under optimization with warnings treated as
errors in the assistant's Python 3.12.14 environment. The project owner's Python
3.14 runs and live Docker inspection remain pending. Passing fixtures does not
prove that every metadata assumption matches the installed Docker/Compose version.

Run from the project root:

```bash
PYTHONPATH=demo python -W error -m unittest discover -s tests -v
PYTHONPATH=demo python -O -W error -m unittest discover -s tests -v
python -m toolkit status
python -m toolkit preflight --image sdt-demo-api:phase1 --release demo-v1
```

A missing-image refusal can be checked without changing containers by selecting a
syntactically valid but locally absent image reference. Verify absence first;
never assume a particular tag is absent. No failure exercise needs to stop the
database or alter existing resources for this batch.

Primary command references checked for this implementation:

- https://docs.docker.com/reference/cli/docker/compose/config/
- https://docs.docker.com/reference/cli/docker/inspect/
- https://docs.docker.com/reference/cli/docker/context/inspect/


### B01: configuration inspection omitted inactive profiles

The owner's first Batch B run passed all 55 tests in normal and optimized modes.
Live status inspection reported api, db and nginx running and returned 0.
Live preflight returned 4 with "Compose service set differs from the supported demo". Batch B acceptance remains open.

Code review found that configuration inspection did not explicitly enable
profiles, despite requiring the init service defined under the tools profile.
The original fake Compose fixture always supplied all four service definitions,
so it did not exercise profile selection. Profile filtering is the suspected
cause of the observed refusal; the terminal output alone does not show which
service definitions were returned.

Fix: configuration inspection now passes --profile "*" to include all service
profiles. The helper accepts only config --format json and refuses other
subcommands, preventing accidental reuse of its all-profile selection for up,
run or down. Configuration inspection does not start init or seed the database.
The expected four-service check remains in place; extra services still fail.

Two regression tests cover profile arguments through a fake Docker executable
and rejection of mutation commands by this helper. The suite now has 57 test
methods. These tests do not substitute for rerunning preflight with real Compose.
Local verification of the fix on the owner's machine remains pending.

Reference: https://docs.docker.com/compose/how-tos/profiles/


### B01 local retest — passed

After applying the profile-inspection correction, all 57 tests passed
normally and under Python optimization, with warnings treated as errors,
on the owner's Python 3.14.10 environment.

Live preflight completed successfully with exit code 0. The selected
candidate and running API resolved to the same immutable image ID.
The earlier service-set refusal did not recur.

This closes B01's pending local retest. It verifies the supported
read-only inspection path for the existing demo, not deployment,
HTTP behavior, release contents, locking, or operation-state handling.
Failure scenarios covered by simulated tests have not all been
reproduced against the live Docker daemon.

## Batch C operation records and locking

The toolkit uses one nonblocking Linux file lock per checkout. Future mutation
commands must hold it from preflight through final recording. The lock file
stays in place so cooperating processes always lock the same file. Linux releases
the lock when the process exits. External Docker commands do not take this lock.

The journal lives under the ignored `.runtime/toolkit/` directory. The current
`state.json` contains the latest operation and the last recorded success. When a
new operation begins, the previous completed record is archived as
`operation-<id>.json`. Files contain the operation ID, image ID, release, outcome
and UTC timestamps. They exclude Docker output and configuration values. Writes
sync a temporary file, replace the destination, then sync its directory.

The caller must record `pending` successfully before asking Docker to replace
anything. Once the result is known, the caller can record `succeeded` or `failed`.
Only success updates the last successful release. If replacement or verification
is interrupted and the outcome is uncertain, leave the record pending. A pending
or invalid snapshot blocks a new operation session. A missing snapshot with
archives also blocks a new session. The corrective batch below also detects a
missing first snapshot when its initialization marker remains. Deleting the entire local journal can erase
that evidence. Reconciliation belongs to Phase 3.

`status` reads the journal without taking the mutation lock and separately
observes Docker. Pending or invalid state returns 6 and still attempts the
Docker observation. If Docker inspection also fails, both problems are reported
and exit 6 takes precedence. A Docker inspection failure alone returns 4.
Batch D will map lock contention to 5 and recording errors to 7 and connect the
journal to live deployment. A recording error after replacement may leave
a pending or just-written record. It must take precedence over success in the
exit code. An interruption that can be reported exits 130 unless saving a
required record also failed. A hard process exit can leave a pending record
without an exit message from the tool.

Batch C uses synthetic operations in temporary directories to exercise real
cross-process locking, abrupt exit, and failed record replacement. The
`deploy` command still returns 3. Running `status` is read-only and is expected
to report no recorded operations on a checkout that has never used the journal.

Run the same unit suite in normal and optimized modes, then run
`python -m toolkit status` against the existing demo. Record local results once
observed.


### Batch C local verification — passed

All 70 tests passed normally and under Python optimization, with warnings
treated as errors, on the owner's Python 3.14.10 environment.

The suite exercised cross-process lock contention, abrupt process exit,
pending-operation refusal, failed record replacement, invalid state,
and preservation of the last successful release using temporary directories.

Live status reported no recorded operations and observed the api, db,
and nginx containers running. Live deployment interruption and recovery
behavior remain pending integration in later work.


## Stopped-API preflight revision

Preflight now permits an owned API container whose state is exited.
Database and proxy containers must still be running, and the database
health check must be healthy. Existing ownership, port, mount and image
checks remain applicable.

The network check requires all running project-container endpoints.
It permits the stopped API endpoint to be absent or retained and rejects
unrelated container endpoints.

Eight regression test methods were added. All 78 tests passed locally
normally and under optimization, with warnings treated as errors.
Live preflight also passed against the existing running stack.

Stopped-API acceptance was exercised using test fixtures. A live
stopped-API exercise and deployment integration remain pending.
This revision supersedes the earlier blanket running-API prerequisite
described in the Batch B record.

## Corrective batch after 7397feb

This batch changes inspection cleanup, journal primitives, tests and documentation.
It does not start containers, implement deployment, or implement reconciliation.

### Journal initialization and upgrades

`initialized.json` contains exactly `{"version": 1, "purpose": "operation-journal"}`.
Under the mutation lock, `begin` atomically writes and synchronizes the marker
before writing pending intent. It does not return an operation ID until the
pending record has been saved. A marker or snapshot write failure aborts begin.
A missing snapshot with a marker or archive is uncertain and blocks mutation.
Malformed, unsupported or symlink markers are refused without overwriting them.

A session that never begins an operation does not create a marker. Read-only
status does not create, repair or migrate state. Valid legacy snapshots without
markers remain readable; a completed legacy snapshot receives a marker before
its next operation begins. Pending legacy state still blocks mutations.
A read racing with first initialization may conservatively report uncertainty.

Partial initialization is not automatically repaired. Missing-marker legacy
compatibility and complete local deletion remain limitations; the marker is
neither backup storage nor tamper-proof evidence.

### Subprocess cleanup and timeout contract

Inspection commands start a new process session. Cleanup sends SIGKILL to the
local process group, including ordinary descendants, then waits up to two seconds
for the direct child. Cleanup failure is reported; timeout is not a daemon
cancellation guarantee. The cleanup budget is separate from command timeout.
A descendant that escapes into another session is outside this mechanism.

For Batch D, a deployment-command timeout must preserve pending intent and return
uncertainty (exit 6), unless a required recording failure takes precedence (7).
Attempt bounded read-only observations with a separate, explicit budget. Report
observed facts but do not convert them into a completed deployment record.
No automatic retry or rollback follows an uncertain timeout. Phase 3 reconciliation
will resolve the pending operation before further mutation. This policy is approved,
but its live deployment implementation and tests remain pending.

### Verification

The suite exercises first-snapshot loss, initialization interruption, marker
validation, synchronization failure, legacy upgrade/refusal, CLI state isolation,
uncertainty precedence, and child-process cleanup. Test operations use temporary
directories and fake Docker executables; they do not change the demo's resources.
Owner-side verification and the live stopped-API exercise passed; see the
owner verification record below.
Assistant-side verification on 17 November 2026: all 94 test methods passed
normally and with `-O`, with warnings treated as errors, using Python 3.12.14.
`pip check` and `git diff --check` passed. This is not an owner-side Python 3.14
result, a live Docker result, or proof of power-loss durability.


### Corrective batch owner verification — passed

All 94 tests passed normally and under Python optimization, with warnings
treated as errors. `pip check` reported no broken requirements.
`git diff --check` passed.

Live status observed the API, database and proxy running and reported no
recorded operations. Running-stack preflight passed; the candidate and current
API image IDs matched. Smoke checks passed directly and through NGINX.

The controlled exercise stopped the API, and live preflight accepted the
stopped, owned container. API startup then completed, both smoke-check paths
passed again, and final preflight observed the API running.

These results verify stopped-API preflight acceptance and subsequent service
recovery. They do not establish deployment of a different image, rollback,
live deployment interruption handling, or power-loss durability.