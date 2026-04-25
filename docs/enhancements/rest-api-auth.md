# REST API Authentication & Authorization

> **Status:** planned (not built)
> **Source:** [vision.md § Integration & surfaces](../vision.md)
> **Priority:** high (blocker for any non-localhost deployment, including the K8s plan)

## What's missing today

The REST API at `/api/v1/*` is wide open. There is no authentication, no per-route authorization, and no audit of who called what. Suitable for a single-process Docker demo on localhost, **not** for any environment with more than one user.

The K8s production-readiness plan has a dedicated phase for this; see [production-readiness-k8s.md § Phase 4](production-readiness-k8s.md). This file is the standalone capability spec; it should land independently of the K8s migration so the in-process Docker mode can also benefit.

## Proposed approach

### Phase 1 — API key (for service-to-service)

- New `api_key` table: `id, name, key_hash (bcrypt), application_id, created_at, expires_at, revoked_at`
- A FastAPI dependency that resolves the bearer token to an `application_id` and rejects unknown / revoked / expired keys
- Every authenticated request gets `request.state.application_id` populated; the SDK Application registration ties API actions back to a tenant

### Phase 2 — User identity + roles (for the Admin UI)

- New `user` table + `user_role` (admin, author, reviewer, viewer)
- OIDC integration (Google / Okta / Azure AD) via `authlib` — no password storage
- Session cookies for the Admin UI; bearer tokens (signed JWT) for API
- Role-based gating on routes:
  - `viewer` — read everything except secrets
  - `author` — can create / edit drafts, can submit runs
  - `reviewer` — can sign approval gates
  - `admin` — full access including quota config and user management

### Phase 3 — Per-application scoping

- Every governed entity already has an `application_entity` mapping (multi-tenant)
- Authenticated requests are filtered to entities mapped to the caller's application(s)
- Cross-tenant access requires `admin` role and is logged separately

## Acceptance criteria

- `/api/v1/*` rejects unauthenticated requests with 401
- API keys can be created, listed, revoked via Admin UI
- OIDC login works for at least Google
- Authorization decisions are themselves logged (who, what route, allow/deny, reason) for compliance
- All existing tests pass with a default test API key injected

## Notes

Coordinate with the K8s plan: Phase 4 there assumes this is in place. Pick one source of truth for the user/role/key tables — both docs should reference the same schema once implemented.
