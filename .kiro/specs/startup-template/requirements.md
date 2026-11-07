# Requirements: Startup Template

## Introduction

The startup template is the single reference architecture Lusiform generates for
every project in the MVP. The PRD calls it "the whole product in MVP": its
quality is the product's quality. This spec defines the Terraform modules, their
parameter schema, the versioning model, and the security posture the template
must hold, so that the generation pipeline (a later spec) can render it
deterministically and the validation gate can pass it.

This spec produces the template files and schema under `templates/`, plus the
tests that guard them. It does not build the rendering engine, the estimate
service, the diagram renderer, or any UI; those consume this template in later
specs. It also does not apply anything to AWS.

Source of truth: the PRD and Technical Design in `docs/`, and the steering files,
especially `tech.md`, `terraform.md`, and `security.md`. The `template_versions`
table and its immutability come from the `foundation` spec.

## Glossary

- **Template**: the fixed startup reference architecture, a set of Terraform
  modules with a parameter schema.
- **Template version**: an immutable, published snapshot of the template,
  identified by semver (for example `1.0.4`) and recorded in `template_versions`.
- **Parameter schema**: the typed, constrained set of inputs a consultant may
  adjust; it defines allowed values and ranges per module.
- **Golden fixture**: stored rendered output for a known parameter set, compared
  byte for byte in tests to prove determinism.

## Requirements

### Requirement 1: Fixed module set

**User Story:** As a consultant, I want one well-formed startup architecture, so
that I can hand a customer a correct, single-region AWS footprint without
designing it myself.

#### Acceptance Criteria

1. THE template SHALL consist of these modules only: networking, compute
   (ECS Fargate), database (RDS PostgreSQL), logging and monitoring (CloudWatch),
   and IAM (least-privilege roles).
2. THE networking module SHALL create a single-region VPC with public, private
   application, and isolated data subnets, and SHALL support one or two
   Availability Zones as a parameter.
3. THE template SHALL NOT include EKS, Aurora, ElastiCache, CloudFront, AWS WAF,
   a third Availability Zone, or Graviton-only constructs.
4. THE template SHALL target a single AWS region per project; it SHALL NOT create
   a secondary or failover region.
5. THE compute module SHALL run the workload on ECS Fargate behind an Application
   Load Balancer.
6. THE database module SHALL provision managed PostgreSQL on RDS, with a standby
   in the second AZ when the AZ-count parameter is two.

### Requirement 2: Parameter schema

**User Story:** As a consultant, I want to adjust sizing and retention within safe
bounds, so that the architecture fits the workload without allowing invalid or
out-of-scope choices.

#### Acceptance Criteria

1. THE template SHALL expose a machine-readable parameter schema with, for each
   parameter, a type, allowed values or range, a default, and the module it
   belongs to.
2. THE schema SHALL include at least: ECS task size (from a fixed set of
   vCPU/memory pairs), minimum tasks, maximum tasks, RDS instance class (from a
   fixed set), storage GB (with a range), backup retention days (with a range),
   Availability Zone count (1 or 2), and log retention days (with a range).
3. WHEN a parameter value is outside its allowed set or range THEN schema
   validation SHALL reject it with a message naming the parameter and the bound.
4. THE schema SHALL define the same allowed values that the Architecture-stage UI
   presents, so the UI and the renderer validate against one source.
5. THE schema SHALL NOT expose a free-form VPC CIDR as an unconstrained text
   field, NAT-mode or region choices beyond those in Requirement 1, or any
   parameter that would select an out-of-scope service.

### Requirement 3: Deterministic, safe output

**User Story:** As a platform owner, I want identical inputs to produce identical,
credential-free output, so that projects are reproducible and safe to hand off.

#### Acceptance Criteria

1. WHEN the template is rendered with the same parameter values and the same
   template version THEN the output SHALL be byte-identical across runs.
2. THE rendered project SHALL include the module files, a root configuration,
   `variables.tf`, `terraform.tfvars.example`, and a generated `README.md`.
3. THE rendered output SHALL contain no hardcoded credentials and no AWS account
   IDs, and a test SHALL assert this on every template change.
4. THE root configuration SHALL declare Terraform `>= 1.10` and a pinned AWS
   provider, and SHALL configure the S3 backend with `use_lockfile = true` and no
   DynamoDB lock table.
5. THE template SHALL treat consultant free-text notes as data only; notes SHALL
   NOT appear in resource names, file names, or interpolated into any resource.

### Requirement 4: Passes the validation gate

**User Story:** As a consultant, I want the template to pass all validators
cleanly, so that generated projects are deployment-ready and trustworthy.

#### Acceptance Criteria

1. THE rendered template SHALL pass `terraform fmt -check`.
2. THE rendered template SHALL pass `terraform init -backend=false` and
   `terraform validate`.
3. THE rendered template SHALL pass `tflint` with the AWS ruleset with no errors.
4. THE rendered template SHALL have zero high-severity Checkov findings on the
   pilot parameter sets.
5. THE template SHALL apply secure defaults required by Checkov, including KMS
   encryption on RDS storage and CloudWatch log groups, no public database
   access, and least-privilege IAM.
6. THE repository SHALL include a deliberately insecure fixture that fails Checkov
   as expected, proving the gate detects violations.

### Requirement 5: Versioning and publication

**User Story:** As a platform operator, I want template changes to create new
immutable versions, so that existing projects stay reproducible and history is
auditable.

#### Acceptance Criteria

1. THE template files SHALL carry a semver version, and a change to any module or
   to the schema SHALL produce a new template version.
2. A published template version SHALL be immutable; the stored files and schema
   for that version SHALL NOT change.
3. THE template version metadata SHALL be recordable in the `template_versions`
   table with a status of draft, published, or retired.
4. WHEN the cross-account sandbox policy must change THEN it SHALL require a new
   template version, because the sandbox role's permissions are scoped to the
   template's resource types.
5. THE template SHALL ship an initial published version suitable for pilot use.

### Requirement 6: Expert review before pilot

**User Story:** As a platform owner, I want an AWS-experienced engineer to review
the template before pilot use, so that consultants never hand a customer a wrong
or insecure architecture.

#### Acceptance Criteria

1. THE initial template version SHALL be reviewed by an AWS-experienced engineer
   before it is marked published and used in a pilot.
2. THE review SHALL cover the module set, the parameter bounds, the security
   defaults, and the cross-account policy scope.
3. UNTIL that review is complete, THE initial version SHALL remain in draft
   status.

## Non-functional requirements

1. Rendering a standard parameter set SHALL be fast enough to support the under
   60-second generation target set in the Technical Design (the renderer is a
   later spec; the template SHALL not contain constructs that defeat that target,
   such as large module counts or remote data lookups at plan time).
2. The template SHALL contain no secret material; any secret is referenced from
   Secrets Manager at deploy time, not stored in the files.
3. Tool versions assumed by the template (Terraform, provider, tflint, Checkov)
   SHALL match the pinned versions in the worker image.

## Out of scope for this spec

- The rendering engine and the architecture graph (generation spec).
- The cost estimate and the AWS Pricing API mapping (generation spec).
- The draw.io diagram and parity check (diagram spec).
- Running the validators as a service (validation spec); this spec only asserts
  the template passes them in tests.
- Applying the template to any AWS account.
