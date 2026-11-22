# Phase 3 recovery contract

Batch A records the owner's choices on the merged Phase 2 base `e960f68`. The commands below describe the interface to implement and test starting in Batch B. Phase 2 already supports explicit deployment by image ID.

## Selecting a target

A read-only target listing should show the operation ID, expected release, short display image ID, verification time, and eligibility reason. Manual rollback takes one full successful operation ID. Resolve that ID from validated local history, check that the record ID matches the lookup, and use its full immutable local image ID. Refuse ambiguous, corrupt or conflicting records, missing images, pending state and unsupported evidence versions. Never substitute another success or pull a moving tag. Multiple successful verifications of the same image are valid distinct records.

The operator can preview the decision with `rollback --to <operation-id> --dry-run`. Preview reads existing evidence without creating files, changing containers, or reserving eligibility. Report the category of any refusal. A real rollback reacquires the existing mutation lock and repeats all checks before writing pending intent. External operators and Docker remain outside that lock.

## One exception for manual use

Default rollback requires equality of both the recorded base Compose file bytes and its fully resolved model, plus the independent evidence below. With explicit `--allow-equivalent-config`, manual rollback may waive only base Compose *byte* equality. The complete supported base model and every other guard must still match. Automatic recovery uses the strict rule. An unconfirmed replacement or pending record goes to reconciliation.

| Observation relative to the selected success | Strict | Manual with flag |
|---|---|---|
| All required evidence matches, target image present | Eligible | Eligible |
| Only a Compose comment or formatting changed, complete model matches | Refuse | Eligible |
| Same raw files, shell supplied a different resolved credential | Refuse | Refuse |
| Environment file, NGINX content, schema evidence, dependency identity, effective service setting or ownership differs | Refuse | Refuse |
| Source/renderer, evidence format, target record, comparison key or runtime observation unsupported or missing | Refuse | Refuse |

“Eligible” permits an attempt. A successful result still requires the existing five verification groups and successful final recording. The exception covers equivalent representations of this project's supported model. It makes no claim about arbitrary Compose projects.

## Evidence to implement

1. At a new verified success, bind the operation ID, checkout/project, release and immutable image ID to versioned compatibility evidence. Capture before and after verification, and require agreement. Phase 2 records retain their historical meaning. Obtain a fresh record by verifying the running release under the new rules. Never infer old evidence from today's files.
2. Capture the raw base Compose file and the full resolved base project separately. Use the same explicit project, directory, env file, all profiles, Compose executable/version and fixed environment for each render and mutation. Shell variables can override file values. Canonicalize JSON objects by key, preserve array order, values and types, and reject ambiguous input or unsupported renderer changes. Compare the entire base model, including the base API image field. Validate the separate toolkit override independently and permit only its image field to change during replacement. Validate the effective merged mutation plan against that one expected substitution.
3. Restrict inputs to the documented single base file, toolkit image override, existing environment file, known proxy bind mount and known demo resources. Reject unsupported external fragments, includes, extra file-backed inputs and service hooks when their full input boundary cannot be established. Bound file sizes, refuse unexpected file types and fail closed on inspection errors. Recheck inputs immediately before replacement. Out-of-band races can still occur.
4. Compare the environment file and mounted NGINX configuration bytes independently. Use the existing ownership, volume, network, mount and port checks. Require matching DB and proxy container and image identities, the expected volume and network identity, and a supported DB schema contract. A conservative first schema check should read actual PostgreSQL metadata for the supported table, columns, types, nullability and primary key and compare with a versioned expected signature. Require the declared compatible contract on the selected release. Document the exact schema projection accepted in Batch B. Fixture reads alone cannot attest to it.
5. A rendered configuration describes desired state. For fresh evidence also check the supported running service settings against that model, including the effective API database connection environment when verifying a running baseline, dependency configuration and proxy mount. Define the supported runtime fields explicitly and refuse unexplained drift within them. Compare secret values only in memory. Failure of the candidate's HTTP verification alone must not prevent a known-compatible target from being considered. Missing independent dependency/schema evidence does prevent it.
6. Proposed storage choice for Batch B: use domain-separated HMAC-SHA-256 comparisons with a random, owner-only key associated with the checkout, for raw file and canonical model evidence, including inputs that may contain credentials. Keep the key outside Git and out of operation records, stdout, error messages and exports. Validate file ownership, permissions and type. Initialize under the lock. Key loss or change invalidates dependent comparisons. A preview must never generate a replacement key. Never persist raw rendered models, credentials or unkeyed secret fingerprints. This assumes a trusted local operator and filesystem.
7. Record target ID, attempt/action, whether the operator requested the exception, whether it was needed, and the independent recovery outcome. Verify the target image and expected release through the existing verifier. Preserve the triggering failed deployment as a failure even when recovery succeeds. For future opt-in automatic recovery capture the verified running baseline before replacement and allow at most one eligible recovery attempt. File/record failure and an unconfirmed command must preserve uncertainty.

The strict dependency-ID rule can refuse an otherwise equivalent database recreation. The fixed schema signature covers only the supported demo. External services, data semantics and arbitrary image behavior exceed this contract. The operator may establish fresh evidence by verifying a supported release in the new environment.

## Acceptance gates for later batches

| Test setup | Required evidence |
|---|---|
| Verify a Phase 3 baseline, deploy v2, select its earlier v1 operation | Full target ID honored, v1 verified, unchanged dependencies, separate operation record |
| Append a comment to the dedicated test Compose file | Default preview refuses, flagged preview permits, actual flagged manual rollback repeats checks and succeeds, automatic eligibility refuses |
| Change a port, an effective environment value through the shell, or a proxy file while keeping its path | Both manual modes refuse before requesting replacement, including the unchanged-YAML shell case |
| Change dependency identity or schema while the catalogue can still answer | Refusal with an actionable reason and no replacement |
| Old/failed target, missing image/key, malformed or pending history | Safe refusal, original evidence retained |
| Change config after a successful preview | Execution reevaluates under lock and refuses changed evidence |
| Inspect CLI output, errors and serialized records with distinct synthetic secret sentinels | No sentinel or raw config disclosure |
| Simulate command timeout or final record failure | No false success or second mutation; documented uncertain/recording result |

Use isolated fixtures for negative tests and a dedicated demo for live verification. Batch B should prove the comment-only pass and real-change refusal on the supported Compose installation before enabling the exception. If that boundary cannot be implemented reliably, keep the exception unavailable and retain strict manual recovery. Batch C defines reconciliation, Batch D integrates opt-in automatic recovery, and Batch E records owner-side live evidence and prepares the Phase 3 PR.

Sources for Compose behavior: [rendering the project model](https://docs.docker.com/reference/cli/docker/compose/config/) and [environment interpolation precedence](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

## Batch B implementation

Run all commands from the project root. The initial baseline must be the running
image. The operator declares that the selected image belongs to the trusted
catalogue workload and expects the `catalogue-v1` schema.

```bash
python -m toolkit baseline --image sdt-demo-api:phase1 --release demo-v1 --schema catalogue-v1
python -m toolkit targets
```

Use the complete operation ID shown for the desired success in place of
`FULL_OPERATION_ID`. A preview reads the local journal and Docker. Each real
attempt repeats selection, preflight and evidence collection under the existing
checkout lock. A successful rollback can itself serve as a later target.
Ordinary Phase 2-style deployments keep their existing journal format.

```bash
python -m toolkit rollback --to FULL_OPERATION_ID --dry-run
python -m toolkit rollback --to FULL_OPERATION_ID
```

For an equivalent Compose edit, add `--allow-equivalent-config` to a manual preview
or attempt. The journal records the selected target, whether the exception was
requested and whether the change in bytes required it. A matching running image
uses verification only. A replacement targets the API alone. The five verification
groups and final journal write determine success. A pending result blocks another
attempt. An operator using Docker directly can still change resources between checks.

### What is compared

- The shipped Compose source accepts blank lines, whole-line comments, line-ending
  changes and trailing whitespace within its supported ASCII syntax. Significant
  source lines must retain the shipped structure. The entire rendered base model
  must also match. Includes and additional input files are outside this boundary.
- Recovery supports the two unquoted password assignments produced by the demo setup.
  It compares the environment file separately from values resolved by Compose.
  Shell-supplied values participate in the resolved model. The NGINX file on the
  host is compared to the file actually visible inside the proxy.
- The renderer identity includes the reported Compose version and local executable
  paths, device/inode, size and change time. Preview renders the proposed image
  override from memory. Replacement also renders the actual stored override. The
  only permitted model difference is the API image field.
- Preflight checks ownership, network membership, mounts, ports, dependency images
  and platform. Recovery additionally checks the expected process user, command,
  entrypoint and environment from the image and service settings. It checks the API
  read-only filesystem, cap drop and security option, and the DB writable mount.
  DB and NGINX container and image IDs, network ID, and volume name, creation time
  and mountpoint participate in the comparison. Docker local volumes expose no
  separate immutable volume ID in this projection.
- A read-only PostgreSQL metadata query expects an ordinary `public.items` table.
  Its visible columns in order are `id integer NOT NULL` and `name text NOT NULL`,
  with the primary key on `id`. This check excludes triggers, other constraints,
  privileges, application semantics and the contents of other tables.
- A random 32-byte comparison key lives under the ignored journal directory with
  mode 0600. HMACs bind the successful operation, full image ID and expected release
  to the evidence. State version 3 carries recovery metadata. Existing version 1
  and 2 records stay readable. A missing key with existing recovery evidence
  blocks baseline registration. Key loss calls for operator investigation.
  Read-only commands never initialize the journal or key. The toolkit assumes a
  trusted operator and filesystem. Applications that share the same checkout lock
  cooperate; the key does not protect against a malicious owner.

### Live acceptance on the dedicated demo

First run the baseline and listing above on healthy v1. Supply its full ID and
the existing, distinct Phase 2 demo-v2 image to the exercise. The script briefly
appends a comment to the project's Compose file. It restores the original bytes
on normal completion or a handled failure, and refuses to overwrite an unexpected
concurrent edit. Keep this file closed for editing during the exercise.

```bash
python scripts/phase3-manual-acceptance.py --to FULL_OPERATION_ID --candidate LOCAL_DEMO_V2_IMAGE
```

The exercise checks the strict and flagged previews, then supplies a different
credential only to a child process and expects refusal. It deploys v2, requests
manual recovery to the selected v1 record, checks both dependency IDs and runs
the smoke tests. If it stops partway, inspect `python -m toolkit status` and the
Compose file before another attempt. A failed or interrupted run can leave v2
running or an operation pending.

The planned Batch B owner-side live exercise passed on 22 November 2026.
See the [combined live results](#combined-live-results) for the later exercises.

### Assistant verification

The final Batch B suite passed all 180 tests on Python 3.14.10 in normal and
optimized modes, with warnings treated as errors. The existing development lock
installed successfully and its dependency check passed.

The new tests use temporary files and a simulated Docker daemon. They exercise
baseline capture, target selection, strict and flagged comparisons, actual code
paths for journal writes, missing/changed/insecure keys, conflicting archives,
failed verification, unconfirmed replacement, final record failure and preservation
of an earlier failed deployment. They check that previews create no journal files
and that synthetic secret values are absent from captured output and JSON records.

During assistant review, the standalone Compose 5.7.1 binary rendered both the
in-memory and stored image override with the expected single-field substitution.
A comment retained the same model. A shell credential override changed the model.
The metadata SQL was also exercised against PostgreSQL 16.2 in single-user mode,
where it accepted the intended table and detected changed nullability.

These additional assistant checks used temporary synthetic inputs. A Docker
daemon was unavailable in the assistant environment. The owner subsequently
ran the existing 180-test suite and the planned live acceptance script against
the PostgreSQL 18 demo stack. Those results are recorded below.

### Owner verification on 22 November 2026

The owner supplied terminal results from the existing EndeavourOS x86_64
environment with Python 3.14.10, Docker Engine 29.9.3 and Compose 5.7.1.
All 180 tests passed in normal and optimized modes with warnings treated as
errors. The host virtual environment passed `pip check`.

Initial inspection found the API, PostgreSQL and NGINX containers stopped after
a system reboot. All three had exit code 0, OOMKilled false and restart policy
`no`. Preflight and baseline registration refused the stopped dependencies.
Starting the existing containers with Compose succeeded, followed by passing
preflight and smoke checks through the direct and proxy routes.

Baseline operation `0560cdf1401e4cfb835d798de89dead5` used verification only and
recorded the already running `demo-v1` as an eligible target. The target listing
continued to display older successful records with their missing-evidence reason.

| Exercise | Observed result |
|---|---|
| Strict preview of the selected baseline | Eligible with no exception needed. |
| Append the acceptance script's temporary Compose comment | Strict preview refused because the Compose bytes differed. |
| Flagged preview with that comment | Eligible with the exception needed. |
| Supply a different application database credential through the child process environment | Both previews and the flagged manual attempt refused the runtime environment mismatch. |
| Check state after these refusals | The script's journal and resource snapshot comparisons passed. |
| Deploy the separate `demo-v2` image | Operation `e5d5b1287999459a92d21ff0591fdca4` replaced the API and passed all five verification groups. |
| Manually recover to the selected v1 record with the flag | Operation `56a9bbcf541f42959a85bd7b4b5e1e65` replaced the API, passed all five groups and recorded the full selected target ID. |
| Check exception attribution | The successful rollback recorded both `exception_requested=True` and `exception_needed=True`. |
| Check dependency identities and restore the Compose file | The script verified that database and NGINX container IDs were retained and the original Compose bytes were restored. |
| Final strict preview, status and smoke checks | The original baseline was strictly eligible again. Status reported a successful v1 rollback and all three containers running. Both HTTP smoke routes passed. |
| Final Git checks | `git diff --check` produced no output and the file list matched the 15 Batch B project files. |

The selected images were:

- v1 was `sha256:4504c0f6d58c69eef9e9b31624432c71eca61da9994cf37e7cec56087ef84a4a`.
- v2 was `sha256:6a42f087ea8ff28db8f47bb5ec030b82471a3dafc006ffa2e0ac2651fbf1cd6c`.

This exercise establishes the recorded manual path on the dedicated demo. It used
a successfully deployed v2 as the current release before restoring v1. An actual
strict manual replacement without the exception, recovery from failed candidate
startup, hard interruption, live recording failure and automatic recovery were
not exercised in this run. The interruption and recording-failure unit cases
use simulated Docker. The results make no availability-duration or zero-downtime
claim. Later batches retain their acceptance requirements.

## Combined Batches C–E

This batch adds reconciliation and automatic recovery. The owner ran the full
combined acceptance script on the dedicated Docker demo. The
[live results](#combined-live-results) record the tested scenarios and limits.

### C. Reconcile a pending operation

Use `status` to find the full pending ID. Preview with:

```bash
python -m toolkit reconcile --operation PENDING_OPERATION_ID
```

Preview shows the intended image and the current owned API container, image
and running state. If its ID or metadata cannot be validated, the command
refuses. Compare the preview with your operator observations. Confirm Docker
or another operator has finished any outstanding work before requesting closure:

```bash
python -m toolkit reconcile --operation PENDING_OPERATION_ID --close-unknown
```

Closure rechecks the exact pending operation and compares two resource
observations under the mutation lock. It can repair the local generated
override in one specific interruption window. The owned API still uses one
image, and the stored override points to the image named in the pending
replacement. The record must identify its action as `replace`. A legacy
record without an action can be closed when the current override is consistent.
After repair, the toolkit verifies the alignment again. A retry
can finish closure after an earlier repair if the pending journal record remains
valid. A missing or corrupt journal requires investigation.

Closure records `closed-unknown` with the observed API ID, image and running
state. It preserves the original requested release, image and operation ID.
The previous verified success still refers to its original operation. The
command issues Docker inspection calls and can write the local override and
journal. It does not run Compose `up`, stop services, or verify HTTP behavior.
The observation and the lock cannot establish whether submitted daemon work
has finished. Once closed, normal preflight and the recovery checks apply to
any next operation.

### D. Deploy with optional automatic recovery

The default deploy command keeps a failed candidate available for inspection or
explicit manual rollback. To opt in, declare the existing catalogue schema
contract with the flag:

```bash
python -m toolkit deploy --image LOCAL_CANDIDATE_IMAGE --release EXPECTED_RELEASE \
  --auto-recover --schema catalogue-v1
```

Use a trusted local candidate compatible with `catalogue-v1`. The most recent
recorded success must refer to the running API and have valid signed recovery
evidence. A strictly eligible Batch B baseline can qualify. The toolkit
rechecks the baseline across all five groups before replacing the API.
Register the running release again when the newest success lacks compatibility
evidence or the supported environment has since changed. For example, a flagged
rollback during the Batch B comment test captured the file bytes with that
comment. A fresh baseline after the comment is removed captures the current
bytes. Automatic recovery requires a different candidate image and uses no
Compose byte exception. No older record is selected automatically.

Both replacement plans render the stored image-only override against the full
base model. After that render, the toolkit checks compatibility again before
submitting the operation. The checks also require the actual API, DB and NGINX
restart policy to match the supported default. If the candidate passes full
verification and its inputs remain stable, the new success includes recovery
evidence and can serve as a future strict baseline. Ordinary deploy operations
continue to use the original verification record.

After Compose returns, the toolkit must observe the intended replacement.
If it cannot confirm that API, the pending operation requires reconciliation.
It binds verification to the observed API container ID and start time. If
verification fails, the recorded candidate failure comes first. Under the same
lock, the toolkit checks that the same API instance remains current and the
baseline still meets the strict compatibility checks. The baseline
image must still be local. A refused second check leaves the deployment failed
and reports why recovery was skipped. Eligible recovery gets a separate pending
record referring to the baseline and the failed deployment. The API replacement,
verification and final recording run once. Neither a timeout or unconfirmed
command, nor a failure to record the deployment result, triggers automatic
recovery. A crash between the two operations can leave the recorded failure
without a recovery attempt.

| Situation | Exit | Journal outcome |
|---|---:|---|
| Candidate verifies | 0 | Successful candidate. |
| Candidate fails verification and recovery is skipped | 1 | Failed candidate with its planned baseline ID. The skip reason is printed. |
| Candidate fails and recovery verifies | 1 | Failed candidate and a separate successful recovery linked to it. |
| Candidate fails and recovery fails verification | 1 | Failed candidate and a separate failed recovery. Prior success stays recorded. |
| Initial checks refuse the opted-in deployment | 4 | No replacement request or new deployment operation. |
| Another toolkit operation holds the lock | 5 | Existing state remains authoritative. |
| A replacement command is unconfirmed | 6 | Pending intent for the uncertain operation, with bounded observations when possible. |
| A required record or override cannot be saved | 7 | Recording failure. Inspect the journal and current service. |
| Operator interrupts the toolkit | 130 | Inspect status. Any outstanding operation remains pending. |

Version 4 records carry the selected automatic baseline, the recovery trigger
or the reconciliation observation. Recovery history validates linked automatic
records before selection. The reader also accepts versions 1–3. Preserve the
journal and use the current reader to interpret it.

### Combined batch live acceptance

Run from the repository root with the already initialized, dedicated Phase 1
image running as `demo-v1`. Resume existing containers with the README procedure
if they stopped after reboot. Confirm the patch and the local unit suite first.

```bash
python scripts/phase3-final-acceptance.py
```

The script builds a separate local test image from the selected demo files in
an isolated temporary directory.
Its API process starts, waits four seconds and exits before serving HTTP.
The build uses the project's pinned base and lock. It may need downloads if
the base or dependencies are absent from the build cache. Keep other toolkit
commands and Compose file edits idle during this exercise. The API is briefly
unavailable while the failure path is exercised.

- The reconciliation stage exits the toolkit at two controlled points. First
  it exits before sending the replacement, and closure preserves the original
  API. Then it exits after Compose returns but before verification is recorded.
  Closure preserves the replacement until an explicit rollback restores v1.
  Both cases test the pending gate, preview and preservation of the prior success.
- The automatic stage verifies that strict opt-in preflight refuses a temporary
  Compose comment, then restores the original file. It deploys the failing
  candidate in default mode and checks that it remains the current stopped API
  until strict manual rollback restores v1. Finally, opted-in deployment of the
  same candidate should fail, recover once to v1, and return exit `1`. The script
  checks the linked records, dependency IDs and both HTTP routes.

The script returns zero after all its checks pass. The expected candidate
deploy exit `1` is checked inside the script. The stages can also run separately
with `--stage reconcile` or `--stage automatic`. If the script stops early or
is interrupted, inspect `python -m toolkit status` and the Compose file before
another mutation. Keep any pending state and any produced candidate image for
diagnosis. A hard interruption during the temporary comment test can leave
that comment in the source file.

### Combined batch verification

The reviewed patch passed 214 tests on Python 3.14.10 in normal and optimized modes
with warnings treated as errors. The dependency check passed. The tests include
real local journal writes, locking, controlled state changes and simulated
Docker. They cover closure and override alignment, the strict baseline gate,
candidate verification failure, successful and failed recovery, missing targets,
resource drift, ambiguous Docker completion and recording failures. Regression
checks cover API replacement by the same image, a changed process start, schema
drift during rendering, a missing automatic history link and a legacy override
mismatch that cannot be attributed to a recorded replacement.

A scratch integration run executed the acceptance driver through the real CLI
and subprocess runner, the Compose 5.7.1 renderer, and both loopback HTTP
routes with simulated container metadata and Docker mutations. It also tested
a local replacement-command timeout and reconciliation.

### Combined live results

On 22 November 2026, the owner ran the reviewed C–E change based on `99834be`
on the existing EndeavourOS Docker demo. After the test-only `/proc` fix, all
214 tests passed in normal and optimized Python with warnings treated as errors.
The development environment passed `pip check`. Before the acceptance run, the
read-only preflight and both HTTP smoke routes passed on the running `demo-v1`.

| Exercise | Observed result |
|---|---|
| Toolkit exited before submitting replacement | Pending operation `6581b99f412e4d439059b24b4e819898` blocked a new deployment. Preview identified the generated override mismatch. Explicit closure aligned it to the original API and preserved the prior success and container ID. |
| Toolkit exited after Compose returned | Pending operation `ae2f8de22e0146e4b34cf7c5642c3682` blocked a new deployment. The test checked that the candidate exited with code `42`. Closure kept the exited candidate in place until strict manual rollback verified v1. |
| Temporary Compose comment | Strict opt-in preflight refused with `compose_bytes` as the reason. The script checked that the journal and resources had stayed the same, then restored the original file bytes. |
| Failed candidate with default deploy | Operation `3958530b7c0848b79f0b6a9eaf8344b7` recorded failure and left the stopped candidate in place. Strict manual rollback `dc8fe1ad0d874d9cac7e7e22afe458cc` verified v1. |
| Failed candidate with automatic recovery enabled | Deployment `81c2a7e791f34b5ba26514a72f35e1a2` remained failed and returned exit `1`. One linked recovery, `b6eeb3ce9c7d4710b55ff94a9828b190`, targeted the last verified v1 record and passed all five verification groups. |
| Final status | The script checked that the database and NGINX container IDs were retained. Status showed a successful recovery to `demo-v1` with all three containers running, and both smoke routes passed. |

The acceptance script completed both stages. These are local results from a
controlled demo. Daemon interruption during replacement, a live filesystem
write failure and downtime measurements remain outside the recorded run.
