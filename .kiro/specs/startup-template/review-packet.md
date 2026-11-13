# Review packet: startup template 1.0.0

For the AWS-experienced reviewer (requirement 6). Template version `1.0.0` stays `draft`
until this review is recorded. The packet covers the four things requirement 6.2 names: the
module set, the parameter bounds, the security defaults, and the cross-account policy scope.
It then lists the decisions only the reviewer can make.

Nothing here has been applied to an AWS account. Every check so far is `fmt`, `validate`,
`tflint`, `checkov`, and Terraform tests against a mocked AWS provider.

Source files are under `templates/startup/1.0.0/`. Tool pins: Terraform 1.10.5, AWS provider
`~> 5.47`, tflint 0.54.0 with AWS ruleset 0.50.0, Checkov 3.4.3.

## 1. Module set

Five modules, 48 resource blocks in 27 Terraform types (`inventory.json`). Scope is fixed: no
EKS, Aurora, ElastiCache, CloudFront, WAF, third AZ, or Graviton.

| Module | Creates |
| --- | --- |
| network | VPC; public and isolated data subnets in two AZs; internet gateway; route tables; restricted default security group; VPC flow log. No NAT gateway and no private application subnets (D3) |
| compute | ECS cluster (Container Insights), task definition, Fargate service in the public subnets with public IPs; public ALB, target group, optional HTTPS listener; task and ALB security groups; Application Auto Scaling on CPU |
| database | RDS PostgreSQL 16, subnet group, parameter group, security group, customer-managed KMS key and alias; RDS-managed master password |
| monitoring | KMS key and alias, KMS-encrypted log groups, four alarms (ALB 5xx, ECS CPU, RDS CPU, RDS free storage) |
| iam | ECS execution and task roles, flow log role, RDS monitoring role |

Please confirm: the module set is right for a 1 to 3 tier startup workload, and nothing
essential is missing or excessive.

## 2. Parameter bounds (`schema.json`)

| Parameter | Allowed | Default |
| --- | --- | --- |
| `compute.task_size` | `0.25vcpu-0.5gb`, `0.5vcpu-1gb`, `1vcpu-2gb`, `2vcpu-4gb` | `0.25vcpu-0.5gb` |
| `compute.min_tasks` | 1 to 10 | 2 |
| `compute.max_tasks` | 2 to 20, at least `min_tasks` | 6 |
| `database.instance_class` | `db.t3.micro`, `db.t3.small`, `db.t3.medium` | `db.t3.micro` |
| `database.storage_gb` | 20 to 1000 | 20 |
| `database.backup_retention_days` | 1 to 35 | 7 |
| `network.az_count` | 1, 2 | 1 |
| `monitoring.log_retention_days` | 7, 14, 30, 90, 365 | 30 |

Note: the database classes are the Intel burstable `db.t3.*` family, not Graviton (`db.t4g.*`),
following the product decision to keep Graviton out of the template (see D13).

## 3. Security defaults

- Encryption: RDS storage and CloudWatch log groups use customer-managed KMS keys with
  rotation; the master password is RDS-managed in Secrets Manager (no password in files).
- Exposure: database not public, accepts PostgreSQL only from the task security group; tasks
  run in public subnets with public IPs (no NAT) and accept traffic only from the ALB, so the
  security group is their only network control; data subnets have no internet route; default security
  group has no rules; egress from tasks is HTTPS to the internet and PostgreSQL in the VPC.
- ALB: drops invalid headers; HTTP by default; HTTPS (with port 80 redirecting to it) only when
  `certificate_arn` is set.
- IAM: no wildcard actions or bare `*` resources (linted by test).
- Operations: flow logs on, Container Insights on, deletion protection and final snapshot on
  by default (variables, so the sandbox can tear down).
- Checkov: 9 failing checks on every fixture, all recorded in `fixtures/checkov-accepted.json`
  with a severity and reason; 37 checks in `must_pass` (encryption, exposure, wildcard IAM,
  hardening) must run and pass. The insecure fixture fails Checkov as intended.

Five accepted findings would be HIGH under the validation spec's wording: `CKV2_AWS_28` (no
WAF), `CKV_AWS_2` and `CKV_AWS_378` (HTTP listener), `CKV_AWS_260` (port 80 open), all LOW
per D2; and `CKV_AWS_333` (ECS tasks have public IPs), MEDIUM per D3. See D1 to D3 and D17.

## 4. Cross-account sandbox policy scope

`sandbox-policy.json` is generated from the inventory, the hand-kept `iam-catalog.json`, and
AWS's Service Authorization Reference. Four managed-policy documents (5,269, 5,868, 5,430,
and 1,045 characters; IAM allows 6,144 each), 52 statements. Removing the NAT gateway and Elastic IP dropped their actions.

- Create requires the `lusiform-managed` request tag; change and delete require the resource
  tag; names are scoped to `lf-*` where the resource has a name.
- `iam:PassRole` is limited to the four named roles and the service receiving each.
- No account ID in the policy (`${aws:PrincipalAccount}`); `aws` partition only.

Known gaps AWS gives no way to scope (listed in `iam-catalog.json` under `known_gaps`):

1. The VPC default security group is created untagged, so revoking its rules and tagging it
   applies to any security group in the account.
2. Application Auto Scaling checks CloudWatch permissions with calls carrying no alarm name,
   so alarm writes apply to every alarm.
3. `ecs:DeregisterTaskDefinition` applies to every task definition.
4. `lf-*` IAM roles and policies can be created; an `lf-*` policy's content is not
   restricted, so the role can grant permissions inside the sandbox account.
5. Services without a `CreateAction` condition gate tag-on-create on the request tag only;
   an untagged KMS key or scaling target could be claimed by tagging it.
6. The RDS-managed secret is limited to the name prefix `rds!`, not tag-gated.
7. All regions in the sandbox account are covered.
8. The Terraform state bucket is not covered; the sandbox spec must add it.

The policy has never run against an account. Its tests show it is consistent with AWS's
reference, not that Terraform succeeds under it (D10, D11).

## 5. Decisions needed

Each row has a proposed default. "Accept" means keep the design as written. Please mark each
with Accept, Change (with what), or Defer, and note the reason.

Status: all of D1 to D17 are settled by the reviewer (2026-11-13). D1 to D3 and D16 were changes and
are implemented; the rest were accepted as proposed. D10 stays open as a pre-pilot task (a real
create and destroy in a throwaway account), which this repository cannot do.

| # | Question | Proposed default | Effect of changing it |
| --- | --- | --- | --- |
| D1 | HTTPS on the ALB (design Q1): HTTP default with optional `certificate_arn`? | **Accepted by reviewer.** HTTP is the default; HTTPS is used only when a certificate is available (port 80 then redirects) | HTTPS-only needs a certificate for every sandbox deploy |
| D2 | Should `CKV2_AWS_28`, `CKV_AWS_2`, `CKV_AWS_378`, `CKV_AWS_260` be HIGH (Q24)? | **Reviewer: LOW**, not blocking. Recorded in `checkov-accepted.json` | If HIGH, no project with the default load balancer passes the gate |
| D3 | NAT gateway per active AZ (Q3). Largest fixed cost | **Reviewer: no NAT gateway.** Tasks run in public subnets with public IPs; the security group is the only network control. No private application subnets. Implemented as removal, not as an option | A NAT option would be a new template version (new parameter, private subnets, NAT, EIP, policy) |
| D4 | One KMS key per module (Q5) | **Accepted by reviewer 2026-11-13** (Accept). | A shared key changes two modules |
| D5 | Deletion protection and fixed-name final snapshot defaults (Q7) | **Accepted by reviewer 2026-11-13** (Accept; sandbox spec sets `deletion_protection = false`). | None to template; sandbox spec work |
| D6 | RDS engine pinned to major `16` (Q8) | **Accepted by reviewer 2026-11-13** (Accept). | A minor pin risks naming a retired version |
| D7 | RDS log exports off, ALB access logs off (Q9, Q10) | **Accepted by reviewer 2026-11-13** (Accept (LOW findings)). | Exports need pre-created encrypted log groups; ALB logs need an S3 bucket the template does not have |
| D8 | `aws_caller_identity` lookup in monitoring and iam (Q11) | **Accepted by reviewer 2026-11-13** (Accept). | Removing it means an account ID input or a looser key policy |
| D9 | Zone names passed as `<region>a` and `<region>b` (Q13) | **Accepted by reviewer 2026-11-13** (Accept). | Lookup makes rendering non-deterministic |
| D10 | Policy assumptions only a real apply can confirm (Q12, Q17, Q18) | **Accepted by reviewer 2026-11-13** (Run a full create and destroy in a throwaway account before the pilot). Outstanding: do the real create/destroy in a throwaway account before the pilot. | A missing action needs a new template version |
| D11 | Known policy gaps in section 4 | **Accepted by reviewer 2026-11-13** (Accept, documented). | Narrowing is not possible for items 1 to 3, 5; item 4 could drop IAM role creation if the task roles are passed in |
| D12 | Deploy-time inputs outside the schema (Q16): `container_image`, `container_port`, `health_check_path`, `certificate_arn`, `deletion_protection`, `skip_final_snapshot` | **Accepted by reviewer 2026-11-13** (Accept). | Moving them into the schema creates a project version per change |
| D13 | Database classes are `db.t3.*` (Intel burstable), not Graviton `db.t4g.*`. Decided by the product owner; reviewer to confirm sizing and that t3 is available for PostgreSQL 16 in the target regions | **Accepted by reviewer 2026-11-13** (Accept). | Changing the family changes the schema, module validation, fixtures, and pricing lookups |
| D14 | Egress limited to HTTPS and PostgreSQL (Q14) | **Accepted by reviewer 2026-11-13** (Accept). | Another port needs a new template version |
| D15 | Estimate gaps (Q21) and the Route 53 line in the Estimate mock (Q4) | **Accepted by reviewer 2026-11-13** (Mock changes; small items stay unpriced). | Adding Route 53 changes inventory and policy |
| D16 | Default `az_count` is 1; two zones is optional | **Reviewer: accepted** (changed from default 2). Subnets still exist in two zones because the ALB and RDS subnet group need them | None |
| D17 | `CKV_AWS_333` (ECS service public IP) accepted as MEDIUM because of D3, and removed from the `must_pass` public-exposure list | **Accepted by reviewer 2026-11-13** (proposed; confirmed). | If not accepted, a NAT option is required |

## 6. Recording the review

After the reviewer's decisions are folded in (task 12.2):

1. Store the review notes (this packet with the decisions marked) and set `review.notes_ref`.
2. Set `review.reviewed_by` and `review.reviewed_at` (ISO date) in `template.json`.
3. Task 12.3: set `status` to `published`, then
   `python -m template_tools.publication manifest startup/1.0.0`.
4. `python -m template_tools.publication check startup/1.0.0` must pass.

Changes the reviewer asks for in modules, the schema, the inventory, or the policy must be
made before step 3, and the golden files and sandbox policy regenerated.
