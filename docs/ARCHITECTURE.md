# Architecture

Status: Phase 0 design baseline. The application and toolkit are not yet
implemented or verified. This document describes intended behavior.

## Purpose

Build a Python command-line tool that deploys a specific application image,
checks essential behavior, and supports recovery to a previous compatible
application release.

The demonstration workload is a minimal read-only catalogue API backed by
PostgreSQL and accessed through NGINX.

## Scope

- One Linux host and one dedicated Docker Compose project.
- Python CLI, FastAPI demonstration API, PostgreSQL, and NGINX.
- Synthetic catalogue data and a fixed database schema.
- Local execution without required paid services or expiring trials.
- Terminal summaries and local JSON operation reports.
- Manual rollback by default.
- Explicit opt-in automatic recovery for eligible image-only changes.

The original diet and medical project repositories and their Docker
resources are outside this project's control.

## Components

- CLI: validates inputs and coordinates operations.
- Docker Compose: defines and runs the demonstration stack.
- API: exposes catalogue, liveness, readiness, and version endpoints.
- PostgreSQL: stores seeded catalogue records in a dedicated named volume.
- NGINX: forwards requests to the API.
- Local state: records release references and operation progress.
- Reports: record verification and recovery outcomes.

The toolkit runs on the host. The demonstration containers do not need
access to the Docker socket.

## Proposed API

- GET /items: returns a bounded catalogue in a predictable order.
- GET /health/live: confirms that the API process can answer.
- GET /health/ready: checks access to the required database table.
- GET /version: returns application release metadata.

Database initialization and repeatable seeding are explicit operator
actions. Seeding must not duplicate records or erase existing data.

The API has no public write endpoints or individual-user accounts.
It is an isolated demonstration, not a public multi-user service.

## Deployment verification

Preflight checks validate configuration, Docker access, image availability,
resource ownership, deployment locking, and recorded operation state before
replacing the application.

The selected image must be resolved to an immutable image identifier.
A mutable tag alone is insufficient to identify a deployed release.

Five post-deployment check types:

1. Application container state during the verification window.
2. API liveness.
3. Expected running image identity and application release metadata.
4. A database-backed catalogue response with expected synthetic content.
5. The catalogue response through NGINX.

Checks have explicit deadlines, request timeouts, and bounded retries.

Readiness is an operational endpoint used during startup and diagnosis.
It does not replace the database-backed catalogue check.

Passing these checks establishes only that the defined checks passed.
It does not prove complete correctness, security, or future availability.

## Recovery policy

Manual rollback is the default. A failed deployment is reported without
automatically replacing it again. Service may remain unavailable until
the operator takes action.

Automatic recovery requires explicit opt-in and a recorded previous
successful release whose image is still available.

It is limited to supported image-only changes under unchanged runtime
configuration, database schema, and dependency arrangement.

Eligibility depends on declared compatibility and the checks the toolkit
can perform. The toolkit cannot prove arbitrary application compatibility.
If required evidence is missing or inconsistent, automatic recovery is
refused.

Rollback restores an application image, not database contents,
configuration changes, or dependency availability.

Recovery is attempted at most once per failed deployment and is verified
separately. A failed deployment returns a nonzero exit code even when
recovery succeeds.

A failed first deployment has no previous release to restore.

## State and interruption handling

Mutating operations share a lock to prevent overlapping toolkit operations.
The lock cannot prevent someone from changing Docker resources manually.

Operation progress is recorded before replacing the application.
The previous successful release reference must not be overwritten by a
failed candidate.

Incomplete operations, inconsistent state, or unreadable state require
inspection before another mutating operation proceeds. Unknown state must
not be treated as success.

Read-only status and diagnostic operations should remain available when
deployment cannot proceed.

The exact state format and reconciliation procedure will be specified
before recovery implementation.

## Reporting

Each operation attempts to save a small record and prints a concise result.

Deployment outcome and recovery outcome are separate fields.
Detailed failures include bounded diagnostic evidence and suggested next
steps. Observations must be distinguished from suspected causes.

Reports must not include secret values, complete environment dumps, or
unfiltered application logs.

If a report cannot be saved, the command must disclose that failure rather
than claim that the report exists.

## Resource and security boundaries

- Operate only on the configured local Docker environment.
- Use a distinct Compose project name and verify resource ownership.
- Refuse to adopt conflicting pre-existing resources silently.
- Bind any published demo ports to loopback.
- Do not publish PostgreSQL to the host.
- Do not explicitly alter host DNS or firewall configuration.
- Docker may manage networking rules as part of normal container operation.
- Do not perform global Docker cleanup.
- Do not delete database volumes during deployment or rollback.
- Keep credentials out of Git, image layers, operation state, and reports.
- Use trusted local configuration and reviewed demonstration images.

Docker access grants substantial control over the host. These boundaries
limit intended toolkit behavior; they do not create a security sandbox.

## Phases and acceptance

0. Foundation: scope, decisions, limitations, README, and ignore rules.
1. Demo stack: clean startup, repeatable seeding, catalogue access, and
   verified health behavior.
2. Deployment: explicit image selection, locking, operation records,
   and the five verification checks.
3. Recovery: manual rollback, eligible automatic recovery, and detection
   and handling of interrupted operations.
4. Diagnostics: DNS/TCP/HTTP observations, structured reports, and
   reproducible failure exercises.
5. Release: clean-install verification, CI evidence, a demonstration,
   and documentation matching actual behavior.

Tests and documentation develop alongside each phase.

## Out of scope

Kubernetes, Terraform, Jenkins, AI classification, public hosting,
application authentication, real health data, database migrations,
database backup and restore, database rollback, high availability,
zero-downtime guarantees, and a web dashboard.