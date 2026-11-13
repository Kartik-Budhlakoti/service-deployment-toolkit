# Decisions

Status: Phase 0 design baseline.

These entries record the selected direction. They do not establish that
the intended behavior has been implemented or verified.

| ID | Decision | Reason and consequence |
|---|---|---|
| D01 | Keep the toolkit and demonstration in one new repository. | Keeps implementation, fixtures, and tests together; the baseline supports one known workload. |
| D02 | Leave the original diet and medical repositories and their Docker resources unchanged. | Preserves earlier work and avoids unintended deployment changes. |
| D03 | Use a minimal read-only catalogue with PostgreSQL. | Provides a meaningful dependency check without nutrition logic or account management. |
| D04 | Run locally using the existing Docker Engine and Compose setup. | Requires no paid hosting, expiring trials, or additional VM; resource usage still needs measurement. |
| D05 | Use manual rollback by default. | A failed check does not establish that reverting the image is the correct remedy; manual mode may leave service unavailable. |
| D06 | Make automatic recovery an explicit opt-in. | Limits recovery to eligible image-only changes under unchanged configuration and schema; compatibility is not universally provable. |
| D07 | Use deterministic checks and reporting rules. | Keeps behavior explainable and avoids an AI dependency. |
| D08 | Attempt to save a small record for every operation. | Preserves release history while keeping terminal output brief; recording failures must be disclosed. |
| D09 | Keep the demonstration schema fixed after Phase 1. | Avoids introducing database migration and downgrade behavior into application rollback. |
| D10 | Use feature branches and pull requests after bootstrap. | Makes changes reviewable; solo pull requests do not imply independent review. |
| D11 | Resolve deployed images to immutable identifiers. | Avoids treating a movable tag as a reliable recovery target. |
| D12 | Keep database backup and restore outside the baseline. | A persistent volume supports container replacement but does not provide disaster recovery. |

## Details to resolve during implementation

Before Phase 1 is complete:
- Supported Python and dependency versions.
- Final Compose project name and available loopback ports.
- Database initialization and fixture verification details.

Before Phase 2 is complete:
- Image identity and release metadata format.
- Check deadlines and retry behavior.
- Deployment lock and operation-state format.
- Exit-code mapping and report fields.
- Resource ownership checks.

Before automatic recovery is enabled in Phase 3:
- Configuration-change detection, including secret-handling limits.
- Supported compatibility declarations and eligibility checks.
- Interrupted-operation reconciliation procedure.
- Behavior when the previous image or required state is unavailable.

These details must be resolved before the dependent behavior is considered
complete. Unresolved details are not evidence that the design is verified.

## Scope-change rule

A new baseline feature must fix an acceptance failure or replace work of
similar effort without weakening existing acceptance criteria.

Other additions are deferred until after the first release.

For a changed decision, record:
- The alternatives considered.
- The selected option and reason.
- The consequences and limitations.
- The affected acceptance criteria.
- Any change to the estimated effort.