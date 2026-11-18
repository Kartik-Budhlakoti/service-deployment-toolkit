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
