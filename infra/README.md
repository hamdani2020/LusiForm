# infra

Terraform for the Lusiform platform itself, in two cloud environments, **staging** and
**prod**: the ECS, RDS, S3, SQS, and Cognito resources that run Lusiform. This is separate
from `templates/`, which is the product's output.

**Development is local, not in the cloud.** `docker compose up` runs every app with Postgres
and LocalStack (S3, SQS, Secrets Manager); see `.kiro/steering/docker.md`. Terraform here
never targets LocalStack: `terraform apply` creates real, billable resources in whatever AWS
account your credentials belong to.

Terraform runs directly on the host (1.10 or later). State lives in S3 with S3-native
locking (`use_lockfile = true`); there is no DynamoDB lock table. The AWS provider is pinned
to `~> 5.47` and each environment commits its `.terraform.lock.hcl`, with hashes for Linux
and macOS.

## Layout

One module per service, so each can be read, planned, and debugged on its own.

```
modules/
  kms/              one customer-managed key per environment (rotation on)
  network/          VPC (2 AZs), subnets, NAT, flow logs
    security_groups.tf   every security group and rule, in one place
  rds/              PostgreSQL 16: KMS, TLS only, backups, managed master password
  cognito/          user pool, hosted login domain, public web client (code + PKCE)
  artifact-bucket/  S3 artifacts: private, KMS, versioned, TLS only
  job-queue/        SQS jobs + dead-letter queue: KMS, TLS only
  ecr/              image repositories: immutable tags, scan on push
  alb/              API load balancer: HTTPS in, HTTPS to targets, HTTP redirects
  ecs-cluster/      the cluster
  api-service/      API service, migrate + bootstrap tasks, their logs
    iam.tf               API execution and task roles
  worker-service/   worker service and its logs (no database inputs at all)
    iam.tf               worker execution and task roles
envs/{staging,prod}/
  main.tf           wires the modules; identical in both environments
  settings.tf       the only per-environment values (sizes, network, protection)
  backend.tf        the environment's state key
  variables.tf, outputs.tf   identical in both environments
```

Two choices worth knowing when debugging:

- **Security groups all live in `network`.** The rules reference each other
  (load balancer → API → database), so the whole traffic picture reads top to bottom in
  `modules/network/security_groups.tf`, not spread over three modules.
- **IAM roles live with the workload that uses them.** If the worker is denied an action,
  look in `modules/worker-service/iam.tf`; for the API, migrate, or bootstrap, in
  `modules/api-service/iam.tf`.

Dependency order: `kms` → `network` → `rds`, `cognito`, `artifact_bucket`, `job_queue`,
`ecr` → `alb`, `ecs_cluster` → `api_service`, `worker_service`.

To work on one service, target its module, for example
`terraform plan -target=module.rds` or `terraform state list module.job_queue`. A change
in `main.tf`, `variables.tf`, or `outputs.tf` must be copied to both environments; a
change in `settings.tf` affects only its own.

| | staging | prod |
| --- | --- | --- |
| Where ECS tasks run | public subnets, public IPs | private subnets, no public IPs |
| NAT gateways | none | 2 (one per AZ) |
| Load balancer | yes (stable HTTPS URL) | yes |
| API / worker tasks | 1 / 1 | 2 / 2 |
| RDS | db.t3.micro, single-AZ, 7-day backups | db.t3.medium, Multi-AZ, 14 days |
| Deletion protection | on | on |
| Log retention | none: kept forever | 365 days |
| Cognito sign-in from `http://localhost:5173` | allowed | not allowed |

**Why staging has no NAT gateway.** To save cost, staging's tasks get public IPs for their
outbound calls (ECR, CloudWatch Logs, Secrets Manager, SQS, S3, Cognito) instead of going
through a NAT gateway. The security groups are the same as prod, so a public IP does not
open them up: the API accepts traffic only from the load balancer, the worker accepts none,
and the database stays in the private subnets with no internet route. Set by
`nat_gateway_count = 0` and `tasks_in_public_subnets = true` in `envs/staging/settings.tf`;
the network module refuses `nat_gateway_count = 0` with tasks in private subnets.

**Staging log retention.** Staging sets no retention (`log_retention_days = null`), so every
log group (API, migrate, bootstrap, worker, VPC flow logs) keeps its events forever and its
storage grows over time. Flow logs are the highest-volume group. Set a number of days in
`envs/staging/settings.tf` to cap them again; prod keeps 365 days.

### Local sign-in with the staging user pool

Staging's web client also allows `http://localhost:5173` as a callback and sign-out URL, so
the local Docker Compose stack can sign in with real Cognito. Prod allows HTTPS origins only.
Anyone running the web app locally can use the staging pool this way, so treat staging users
as test accounts.

1. Get the staging values: `terraform -chdir=infra/envs/staging output web_app_settings` and
   `terraform -chdir=infra/envs/staging output cognito_user_pool_id`.
2. In the repo-root `.env` (git-ignored), set:
   - `VITE_COGNITO_DOMAIN` and `VITE_COGNITO_CLIENT_ID` (from `web_app_settings`), for the
     web app;
   - `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, and `COGNITO_APP_CLIENT_ID` (the same client
     id), so the local API verifies the staging pool's tokens.
3. Create a test user in the staging pool (`aws cognito-idp admin-create-user`, as in
   "First platform operator" below) and read its `sub`.
4. Link it in the **local** database, which is separate from staging's:
   `docker compose run --rm api python -m app.bootstrap_operator --partner-name Lusiform --email you@example.com --cognito-sub SUB`.
   Only the first operator can be created this way; other users arrive with the admin pages
   (agent-and-admin spec).
5. Restart so the settings are read: `docker compose up -d --force-recreate web api`, then
   open http://localhost:5173 and click "Sign in".

## Security properties

- **Encryption at rest:** RDS, Performance Insights, the RDS master secret, S3, SQS, ECR,
  and every CloudWatch log group use the environment's KMS key.
- **In transit:** the ALB accepts TLS 1.2+ (HTTP only redirects to HTTPS), forwards to the
  API over HTTPS, and RDS has `rds.force_ssl = 1`. The bucket and queues deny non-TLS
  requests.
- **Network:** the database runs in private subnets with no internet route and accepts
  connections only from the API security group (API, migrate, bootstrap). In prod the
  services also run in private subnets with no public IPs; in staging they run in public
  subnets with public IPs (see above). Either way the API accepts traffic only from the load
  balancer, and the worker has no ingress and no network path to the database.
- **IAM:** each workload has its own execution role and task role, trusted only by ECS in
  this account and region (`aws:SourceAccount` and `aws:SourceArn`).
  - The **worker task role** can use only the job queue and the artifact bucket.
  - The **API task role** can enqueue jobs and read artifacts.
  - **Migrate and bootstrap** have no task role.
  - Only the API's execution role can read the database secret.
- **Auth:** invitation-only user pool, no federation, email and password, optional TOTP
  MFA. The web client is public (no secret), authorization code only, with token revocation
  on and access tokens valid for one hour.
- **Secrets:** the RDS master password is generated by RDS into Secrets Manager. It is
  never in Terraform variables, state, or images; the API reads it as `DB_PASSWORD` from
  the secret.
- **No account IDs** are hardcoded; they come from `aws_caller_identity`.

## Commands

Plan and apply are deliberate, manual steps. Nothing here runs `apply` automatically.

```
cd infra/envs/staging
cp backend.hcl.example backend.hcl          # state bucket + region (git-ignored)
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive ../..
terraform validate
terraform plan -out=plan.tfplan             # review, then: terraform apply plan.tfplan
```

Validation without AWS access (what CI-style checks use):

```
terraform -chdir=infra/envs/staging init -backend=false
terraform -chdir=infra/envs/staging validate
```

Module tests, with a mocked AWS provider (no credentials, no AWS calls). The network test
checks where tasks run in each environment and that "no NAT, private tasks" is refused:

```
cd infra/modules/network && terraform init -backend=false && terraform test
```

## One-off tasks

Both use the API image and the API security group, in the same subnets as the services.
Get the subnets, security group, and whether a public IP is needed from
`terraform output one_off_tasks`: staging needs `assignPublicIp=ENABLED`, prod
`assignPublicIp=DISABLED`. The examples below use staging.

### Migrations (before each API rollout)

```
aws ecs run-task --cluster lusiform-staging --launch-type FARGATE \
  --task-definition lusiform-staging-migrate \
  --network-configuration 'awsvpcConfiguration={subnets=[SUBNET_A,SUBNET_B],securityGroups=[API_SG],assignPublicIp=ENABLED}'
```

Wait for the task to stop with exit code 0 before updating the API service.

### First platform operator (foundation task 11.2)

Migrations stay data-free, so the first `platform_operator` is created by this separate
task. It refuses to run if any platform operator already exists. Concurrent runs are
serialised, so at most one operator is ever created this way. Every later operator is
added through the admin routes. In one transaction it creates:

- a partner for Lusiform staff;
- an **active** user linked to the Cognito `sub`;
- the `platform_operator` role;
- an `audit_events` row (`bootstrap.platform_operator.create`).

1. Create the Cognito user. Cognito emails a temporary password.
   ```
   aws cognito-idp admin-create-user --user-pool-id POOL_ID \
     --username ops@example.com \
     --user-attributes Name=email,Value=ops@example.com Name=email_verified,Value=true \
     --desired-delivery-mediums EMAIL
   aws cognito-idp admin-get-user --user-pool-id POOL_ID --username ops@example.com \
     --query 'UserAttributes[?Name==`sub`].Value' --output text      # -> SUB
   ```
2. Run the bootstrap task with that `sub`:
   ```
   aws ecs run-task --cluster lusiform-staging --launch-type FARGATE \
     --task-definition lusiform-staging-bootstrap \
     --network-configuration 'awsvpcConfiguration={subnets=[SUBNET_A,SUBNET_B],securityGroups=[API_SG],assignPublicIp=ENABLED}' \
     --overrides '{"containerOverrides":[{"name":"bootstrap","command":["python","-m","app.bootstrap_operator","--partner-name","Lusiform","--email","ops@example.com","--cognito-sub","SUB"]}]}'
   ```
   Exit code 0 means created; 1 means refused (the reason is in the
   `/lusiform/staging/bootstrap` log group). The log records ids, not the email.
3. The operator signs in through the hosted login and sets a new password.

Locally, against the Compose database:

```
docker compose run --rm api python -m app.bootstrap_operator \
  --partner-name Lusiform --email ops@example.com --cognito-sub SUB
```

## Before the first apply (known gaps)

These are not wired yet. The configuration validates, but an apply today would not produce
a working API:

1. **API database settings.** ECS passes `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
   `DB_SSLMODE` and `DB_PASSWORD` from the RDS-managed secret. The API currently reads only
   a single `DATABASE_URL`, so `ApiSettings` must build the URL from these parts.
2. **TLS in the API container.** The target group and health check use HTTPS on 8443
   (`security.md`: TLS from the ALB to the service). The production API image still runs
   plain uvicorn on 8000; it needs to serve TLS on 8443 (for example, a certificate
   generated at start-up, which the ALB accepts without validating). The image must also run
   with a read-only root filesystem as user 10001.
3. **The state bucket** and the **ACM certificate** are created outside this
   configuration.
4. **The web app's hosting** is not defined here.
5. **Hosted login branding** to match the Stitch Sign In screen is not defined here either.
6. **Image tags.** Images must be pushed to the ECR repositories before the services
   are created.
7. **Sandbox roles.** The worker's sandbox plan and apply roles, and the trust for partner
   sandbox accounts, belong to the `sandbox-deployment` spec. The worker task role
   deliberately has no `sts:AssumeRole` yet.

## Checkov findings accepted for now

Scanned per environment with the worker image's pinned Checkov, for example
`checkov -d infra/envs/prod`. Prod passes 315 checks with 15 open; staging passes 306 with
18 open. These remain open in both, with the reason for each:

| Check | Why it is open |
| --- | --- |
| Security groups not attached (4) | False positive: the groups are created in `network` and attached in `alb`, `rds`, and the service modules; Checkov does not follow ids across modules |
| KMS key policy uses `*` resources (3) | Standard key-policy form: in a key policy `*` means this key; the first statement delegates to IAM |
| Port 80 open on the ALB | Listener only redirects to HTTPS |
| AZ data source not pinned | The first two AZs are used; pin by zone ID if the account's AZ list changes |
| RDS enhanced monitoring | Needs a monitoring role; Performance Insights is on |
| ALB access logs, S3 access logs | Need a separate log bucket; to decide before pilot |
| WAF on the ALB | Platform decision, not yet made |
| S3 cross-region replication, event notifications | Single-region MVP; artifacts can be regenerated |

Staging additionally flags public IPs on the two ECS services and Multi-AZ off, both
deliberate cost choices in `envs/staging/settings.tf`; prod has neither.
