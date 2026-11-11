# Verification: Foundation (task 12)

What proves each acceptance criterion in `requirements.md`, and what is not covered.
Test paths are relative to the package (`api/`, `web/`, `worker/`, `common/`, `infra/`).

## 12.1 Full run (all in containers, except Terraform on the host)

| Check | Result |
| --- | --- |
| `common`: ruff, ruff format, mypy, pytest | clean; 24 passed |
| `api`: ruff, ruff format, mypy, pytest (includes migrations, schema, isolation) | clean; 227 passed |
| Tenant isolation suite (`api/tests/isolation`) | 74 passed |
| Migration round trip (`api/tests/test_migrations.py`) | 3 passed |
| Tenant-access guard (`python -m tools.check_tenant_access app` + its tests) | 27 files, no violations; 53 passed |
| `worker`: ruff, ruff format, mypy, pytest | clean; 26 passed |
| `web`: eslint, tsc, vitest, production build | clean; 34 passed; build ok |
| `infra`: `terraform fmt`, `validate` (staging, prod), module tests (mocked AWS) | clean; valid; alb 4, cognito 5, network 7 passed |
| CI `infra` job script, under the pinned Terraform 1.10.5 | passes; fails if a module's tests run zero cases |

## Requirement 1: Monorepo scaffolding

| AC | Proof |
| --- | --- |
| 1.1 directories | `api/`, `worker/`, `web/`, `templates/`, `infra/` at the repo root |
| 1.2 API serves health under `/api` | `api/tests/test_health.py`; `GET /api/health` returned 200 from the running stack |
| 1.3 web builds and serves the shell | `pnpm build`; `web/src/App.test.tsx` (authenticated shell) |
| 1.4 worker starts, reads config, polls | `worker/tests/test_main.py`; ran against LocalStack: received a job, left it on the queue, exit 0 on SIGTERM |
| 1.5 single-run commands recorded | `.kiro/steering/tech.md`, "Commands" |
| 1.6 CI runs lint, type checks, tests per package | `.github/workflows/ci.yml`: common, api, worker, web, isolation-suite, lint-guard, infra |

## Requirement 2: Authentication with Cognito

| AC | Proof |
| --- | --- |
| 2.1 hosted login, email and password, no federation | `infra/modules/cognito` (invitation only, `supported_identity_providers = ["COGNITO"]`); `modules/cognito/tests`. Live on staging: the hosted login accepts the web client with the localhost callback and refuses an unregistered one (`redirect_mismatch`). **Full sign-in done:** a real staging user (`FORCE_CHANGE_PASSWORD`) signed in through the hosted login, set a new password, and reached the Projects shell; the local API answered `/api/me` with 200 for the linked platform operator |
| 2.2 401 for missing, expired, invalid tokens | `api/tests/test_auth.py` (expired, bad signature, wrong issuer, wrong client, ID token, missing claims, unsigned, HMAC confusion). Live: the local API fetched staging's real signing keys (2) and rejected forged tokens with 401 |
| 2.3 identity, partner, roles from token and database | `test_me_returns_identity_from_the_database`, `test_self_endpoints_return_only_the_callers_own_identity` |
| 2.4 short-lived access tokens with refresh, no API keys | Cognito web client: 60-minute access tokens, 12-hour refresh, token revocation on; `web/src/auth/client.test.ts` (refresh before expiry, single shared refresh, rejected refresh clears the session) |
| 2.5 403 without an active record | `test_inactive_user_or_suspended_partner_gets_403`, `test_valid_token_without_a_user_record_gets_403` |
| 2.6 web sends unauthenticated users to the hosted login; no long-lived secret | `App.test.tsx`: landing page, "Sign in" redirects with PKCE; no token in local or session storage or cookies after sign-in. See gap 3 |

## Requirement 3: Data model and migrations

| AC | Proof |
| --- | --- |
| 3.1 all 19 tables | `test_models_cover_exactly_the_nineteen_tables`, `test_upgrade_downgrade_round_trip_is_clean` |
| 3.2 UUID keys, `partner_id` FK to `partners` | `test_tenant_tables_have_partner_fk_and_uuid_pks` |
| 3.3 email unique per partner | `test_email_unique_per_partner` |
| 3.4 role limited to the three roles | `test_valid_roles_accepted`, `test_invalid_role_rejected` |
| 3.5 forward and back cleanly; one-off task | `test_upgrade_downgrade_round_trip_is_clean`, `test_models_match_migration`; Compose `migrate` service; ECS `migrate` task definition |
| 3.6 versions immutable | `test_protected_tables_reject_update_delete_truncate`, `test_template_version_content_is_immutable_but_status_advances` |
| 3.7 append-only tables | the same trigger tests; `test_append_only_repository_has_no_mutation_path`; `test_audit_rows_cannot_be_updated_or_deleted` |
| 3.8 no secret values | `test_no_column_holds_a_secret` (`external_id_ref` only) |

## Requirement 4: Repository layer and tenant isolation

| AC | Proof |
| --- | --- |
| 4.1 one sanctioned path | `api/app/data/`; enforced by the tenant-access guard |
| 4.2 `partner_id` applied to every query | `test_every_tenant_repository_query_is_filtered_by_partner`; scoping tests in `test_repositories.py` |
| 4.3 cross-partner looks like not found (404) | `test_not_found_maps_to_identical_404`; isolation harness (`assert_cross_partner_refused`) |
| 4.4 operator cross-partner access audited | `test_operator_lists_all_partners_and_the_access_is_audited`, `test_unaudited_access_is_impossible` |
| 4.5 automated check fails the build | `tools/check_tenant_access.py`, `tests/test_tenant_guard.py`, CI `lint-guard` |
| 4.6 two-partner isolation suite in CI | `api/tests/isolation` (74 passed), CI `isolation-suite`. See gap 4 |

## Requirement 5: Authorization by role

| AC | Proof |
| --- | --- |
| 5.1 admin routes need partner_admin or platform_operator | `test_role_gating_matrix` |
| 5.2 operator routes need platform_operator | `test_role_gating_matrix`; `test_non_operators_and_anonymous_are_refused_and_nothing_is_audited` |
| 5.3 decision from database roles, not client values | `test_client_supplied_roles_have_no_effect` |

## Requirement 6: Audit and observability baseline

| AC | Proof |
| --- | --- |
| 6.1 audit row with actor, partner, action, target, before/after | `api/tests/test_audit.py` (atomic with the write, rolled back together, sanitised). See gap 5 |
| 6.2 structured logs with request, partner, user ids | `common/tests/test_common.py`; `test_access_log_is_json_with_request_id`; `test_authenticated_request_logs_carry_partner_and_user_ids` (access log and a sync handler's log; the next anonymous request does not inherit them). See "Found by the live check" |
| 6.3 no intake free text, secrets, or credentials in logs | redaction tests in `common/tests/test_common.py`; `test_message_bodies_never_reach_the_logs` (worker) |

## Non-functional requirements

| NFR | Proof |
| --- | --- |
| 1 encrypted at rest (KMS), separated by `partner_id` | `infra/modules/kms`, `rds`, `artifact-bucket`, `job-queue`, `ecr`, log groups; schema tests for `partner_id` |
| 2 JWT on every protected route; only health is open | `test_health_stays_public_and_everything_else_requires_context` |
| 3 isolation proven, zero cross-partner reads or writes | isolation suite: 74 passed |
| 4 dependencies pinned | exact pins in `pyproject.toml` and `package.json`; `uv.lock`, `pnpm-lock.yaml`, `.terraform.lock.hcl` (Linux and macOS hashes) |

## Gaps and caveats

1. **CI has not run on GitHub.** Nothing is committed or pushed, so the workflow,
   including the new `infra` job, has only been checked locally. Blocking merges on
   `isolation-suite` and `lint-guard` also needs a branch-protection rule.
2. **Live sign-in** (2.1) is done against staging's real pool, with one user. Sign-in for
   other roles (consultant, partner admin) needs the admin pages that create users
   (agent-and-admin spec).
3. **2.6 wording:** a signed-out visitor sees the landing page, and its "Sign in" button
   goes to the hosted login, instead of an automatic redirect. This follows the Stitch
   landing page design chosen during task 9.
4. **Isolation for tenant resource routes:** none exist yet, so the harness is proven with
   a scoped and a deliberately leaky probe route. Real routes join the endpoint table in
   later specs; the suite fails if a registered route is missing from it.
5. **Admin writes and generation/deployment actions** (6.1, 5.1) have no routes yet; the
   audit helper and role gating are proven with repository calls and probe routes.
6. **The API cannot run on ECS yet:** it must build its database URL from the separate
   `DB_*` settings, and serve TLS on 8443 (`infra/README.md`, "Before the first apply").
7. **Staging serves plain HTTP** until it has a certificate: a deliberate, staging-only
   exception to "TLS everywhere".

## Found by the live check

The real sign-in showed that request logs for authenticated calls had **no partner or
user id** (6.2). `get_request_context` was a sync dependency, so FastAPI ran it in a worker
thread, and the ids it bound to the log context were lost when it returned; the access log
and the handler's own logs never saw them. The mocked tests only checked the access log of
the anonymous health route, so they did not catch it. Fixed by making the dependency async
(the token check and database lookup still run in the threadpool). The new test fails with
the old code (`KeyError: 'partner_id'`) and passes with the fix.

