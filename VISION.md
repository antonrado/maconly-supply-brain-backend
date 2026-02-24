# VISION

## Project identity
- **Name**: maconly-supply-brain-backend
- **Stack**: FastAPI + PostgreSQL + Docker Compose
- **Purpose**: Internal decision-support backend for MACONLY supply planning and order proposals, with a path to future productization.

## Product goals
1. Keep a stable and testable Planning Core v1 API contract.
2. Keep business logic in services/core layers (not in routers).
3. Preserve monitoring reliability in multi-instance deployments with a single snapshot writer.
4. Make operations reproducible via explicit commands and repo-tracked docs.

## Current implementation anchors (verified in code)
- FastAPI app boots and mounts `/api/v1` routes.
- Monitoring scheduler exists and is started on app startup.
- Monitoring scheduler uses PostgreSQL advisory lock on a dedicated raw DB connection.
- Monitoring APIs include:
  - `GET /api/v1/planning/monitoring/timeseries`
  - `GET /api/v1/planning/monitoring/risk-focus`
- Planning Core v1 endpoints include:
  - `GET /api/v1/planning/core/health`
  - `POST /api/v1/planning/core/proposal`

## Working principles from this thread
- We use **agent coding** (goal -> plan -> multi-file edits -> checks -> fix -> report).
- Context must live in repo docs, not only in chat.
- Requests to the agent should be machine-readable and unambiguous.
- If the requested format is RAW OUTPUT only, return raw output only.

## Non-goals for now
- Full optimization engine (MOQ/lead-time constrained solver) is not finalized yet.
- Product concerns (auth, billing, multi-tenant) are deferred until explicit productization phase.
