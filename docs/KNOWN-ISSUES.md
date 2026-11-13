# Known Issues and Limitations

Status: Phase 0. The toolkit has not been implemented or verified.

## Verified implementation defects

Not applicable yet: there is no toolkit implementation to assess.

This section will record reproduced defects as implementation proceeds.
An empty defect list must not be presented as proof of correctness.

## Deliberate limitations

- Supports one Linux host and one demonstration stack.
- Deployment and manual recovery may interrupt service.
- No high-availability or zero-downtime guarantee.
- Rollback restores an application image, not database contents,
  configuration changes, or failed dependencies.
- Automatic recovery supports only explicitly eligible image-only changes.
- A previous successful release is not guaranteed to work under changed
  external conditions.
- Persistent storage is not a backup.
- Diagnostic observations do not always establish a root cause.
- Local operation records are not tamper-proof audit records.
- The demonstration uses synthetic data and is not a public multi-user
  service.
- There is no continuous monitoring or general self-healing behavior.
- The deployment lock coordinates toolkit operations, not external
  Docker commands.
- The toolkit assumes trusted operators, configuration, and demo images.
- No compatibility claim is made for untested environments or versions.

## Unverified behavior and assumptions

- Dependency compatibility with the selected Python version.
- Actual memory, disk, and startup-time requirements.
- Complete clean-install behavior.
- Correct targeting of project-owned Docker resources.
- Deployment verification and recovery behavior.
- Behavior after interruption, inconsistent state, or rollback failure.
- Configuration-change detection, including its handling of secrets.
- Report redaction and handling of report-write failures.
- Availability of the selected local ports at execution time.

These items must be tested or explicitly bounded before the relevant
phase is accepted.

## Defect format

For each reproduced defect, record:

- Identifier and short description.
- Affected version or commit.
- Reproduction steps.
- Expected and observed behavior.
- Impact and workaround, if available.
- Status and verification evidence.

Suspected defects must be labeled as unconfirmed until reproduced or
otherwise supported by evidence.

A failure of a core acceptance criterion blocks the relevant phase.
It must not be relabeled as an acceptable limitation simply to finish.