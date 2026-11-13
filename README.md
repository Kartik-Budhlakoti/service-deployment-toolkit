# Service Deployment Toolkit

A small Python command-line tool for deploying a containerized application,
checking that it works, and helping restore a previous release when a
deployment fails.

## Why this project

Building a Docker image does not tell us whether the application will work
after deployment. It might start but fail to reach its database, serve the
wrong version, or be unreachable through its reverse proxy.

This project focuses on that gap: checking the running application and
making failed deployments easier to investigate and recover from.

## Current status

Phase 0 — scope and design.

The toolkit is not implemented yet. The documents in this repository
describe the intended behavior, not completed features.

## What it will do

The first version will operate one demonstration stack on a Linux host:

- A small FastAPI catalogue with synthetic data.
- PostgreSQL for storage.
- NGINX as the request entry point.

The toolkit will check the application container, API liveness, release
identity, database-backed responses, and the request path through NGINX.

Rollback will be manual by default. Automatic recovery will require
explicit opt-in and will be limited to supported image-only changes under
unchanged configuration and database schema.

Each operation will print a short result and attempt to save a local JSON
record. If deployment or recovery fails, the output will explain which
checks failed without claiming to know more than the evidence shows.

## Why a small catalogue?

The application is deliberately simple so the project can focus on
deployment and recovery behavior.

It keeps a real database dependency without adding user accounts,
recommendation logic, or unrelated application features.

## Boundaries

The baseline will run locally without required paid services or expiring
trials. It will target its own Docker resources and leave other projects
alone.

This is not a general-purpose orchestration platform. It will not provide
zero-downtime deployments, high availability, database rollback, or
continuous self-healing.

Restoring an older application image will not undo database changes or
repair an unavailable dependency.

## Project documents

- [Architecture](docs/ARCHITECTURE.md) — scope, components, checks, and recovery behavior.
- [Decisions](docs/DECISIONS.md) — choices, alternatives, and trade-offs.
- [Known issues and limitations](docs/KNOWN-ISSUES.md) — boundaries and behavior still to verify.

## Development

Work is divided into phases, starting with the demonstration stack,
followed by deployment checks, recovery, diagnostics, and release
verification.

Changes use feature branches and pull requests. Setup instructions and
demonstration commands will be added as they are implemented and tested.

## License

This project is licensed under the [MIT License](LICENSE).