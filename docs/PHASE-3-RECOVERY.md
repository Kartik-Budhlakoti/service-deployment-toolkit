# Phase 3 recovery contract

Batch A records the owner's choices on the merged Phase 2 base `e960f68`. The commands below describe the interface to implement and test starting in Batch B. Phase 2 already supports explicit deployment by image ID.

## Selecting a target

A read-only target listing should show the operation ID, expected release, short display image ID, verification time, and eligibility reason. Manual rollback takes one full successful operation ID. Resolve that ID from validated local history, check that the record ID matches the lookup, and use its full immutable local image ID. Refuse ambiguous, corrupt or conflicting records, missing images, pending state and unsupported evidence versions. Never substitute another success or pull a moving tag. Multiple successful verifications of the same image are valid distinct records.

The operator can preview the decision with `rollback --to <operation-id> --dry-run`. Preview reads existing evidence without creating files, changing containers, or reserving eligibility. Report the category of any refusal. A real rollback reacquires the existing mutation lock and repeats all checks before writing pending intent. External operators and Docker remain outside that lock.

## One exception for manual use

Default rollback requires equality of both the recorded base Compose file bytes and its fully resolved model, plus the independent evidence below. With explicit `--allow-equivalent-config`, manual rollback may waive only base Compose *byte* equality. The complete supported base model and every other guard must still match. Automatic recovery always uses the strict rule. An unconfirmed replacement or pending record goes to reconciliation.

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
Reconciliation and automatic rollback remain later work.

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
