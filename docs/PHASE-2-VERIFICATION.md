# Phase 2 contract and verification

## Batch A: command interface

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
environment. All 25 unit tests passed normally and under optimization, with
warnings treated as errors. Manual command checks confirmed help output,
validation exit code 0, and unavailable deployment/status exit code 3.
These results do not establish Docker integration or deployment behavior.

Append later batch evidence here; do not mark planned checks as completed.
