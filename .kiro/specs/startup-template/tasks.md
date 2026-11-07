# Implementation Plan: Startup Template

Tasks build in order. Each cites the requirements it satisfies (see
`requirements.md`) and follows `design.md`. This spec depends on `foundation`
being scaffolded (the `templates/` directory, CI, and `template_versions` table)
but does not need the API or web to be running. Never run `terraform apply`
against any AWS account in this spec; stop at `fmt`, `validate`, `tflint`, and
`checkov`.

- [ ] 1. Set up the template package and tooling
  - [ ] 1.1 Create the version directory and metadata
    - Create `templates/startup/1.0.0/` with `template.json` (status `draft`,
      review fields null), the `modules/`, `root/`, and `fixtures/` folders, and
      a `templates/README.md` explaining the layout and versioning rules.
    - _Requirements: 5.1, 5.3, 5.5_
  - [ ] 1.2 Pin and document the tool versions
    - Pin Terraform (`>= 1.10`), the AWS provider (`~> 5.47`), tflint, and
      Checkov, and record them in `template.json`. These must match the worker
      image pins.
    - Add a test-runner script that installs or locates these exact versions
      for local and CI use.
    - _Requirements: 3.4, NFR 3_
  - [ ] 1.3 Add a CI job for the template
    - Run schema tests, module validation, the insecure-fixture check, the
      credential scan, determinism, inventory, immutability, and review-gate
      tests. This job must pass for the pipeline to pass.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

- [ ] 2. Define the parameter schema
  - [ ] 2.1 Write `schema.json`
    - Define the eight parameters from `design.md` with type, allowed values or
      range, default, and owning module. Include the cross-field rule
      `max_tasks >= min_tasks`.
    - Do not add any parameter that selects an out-of-scope service, a free-form
      CIDR, a NAT mode, or a region choice beyond a single region.
    - _Requirements: 2.1, 2.2, 2.5_
  - [ ] 2.2 Implement schema validation and error messages
    - A small validator that rejects out-of-range or wrong-type values with a
      message naming the parameter and the bound.
    - _Requirements: 2.3_
  - [ ] 2.3 Write schema tests
    - Defaults, minimums, and maximums pass; each invalid value is rejected with
      the expected message; the cross-field rule is enforced.
    - Add a check that the allowed values match the ones shown on the
      Architecture-stage designs so the UI and the renderer cannot drift.
    - _Requirements: 2.3, 2.4_

- [ ] 3. Build the network module
  - [ ] 3.1 Implement VPC, subnets, and routing
    - One VPC; public, private application, and isolated data subnets in two AZs
      always; internet gateway; route tables; no internet route for data subnets.
    - _Requirements: 1.2, 1.4_
  - [ ] 3.2 Implement NAT, default security group, and flow logs
    - A NAT gateway per active AZ driven by `az_count`; restrict the default
      security group; enable VPC flow logs to CloudWatch with KMS.
    - _Requirements: 1.2, 4.5_
  - [ ] 3.3 Expose outputs and write module tests
    - Outputs: VPC id, subnet ids by tier, NAT count. Test `az_count = 1` and
      `az_count = 2` produce the expected NAT and subnet counts.
    - _Requirements: 1.2_

- [ ] 4. Build the monitoring module
  - [ ] 4.1 Implement the KMS-encrypted log group and alarms
    - A CloudWatch log group encrypted with a customer-managed KMS key (rotation
      on), retention from `log_retention_days`, and alarms for ALB 5xx, ECS CPU,
      RDS CPU, and RDS free storage.
    - _Requirements: 1.1, 4.5_

- [ ] 5. Build the IAM module
  - [ ] 5.1 Implement task execution and task roles
    - ECS task execution role with the managed execution policy, and a task role
      with only declared permissions. No wildcard actions or resources.
    - _Requirements: 1.1, 4.5_
  - [ ] 5.2 Add an IAM policy lint test
    - Fail on any `*` action or `*` resource in the module's policies.
    - _Requirements: 4.5_

- [ ] 6. Build the database module
  - [ ] 6.1 Implement RDS PostgreSQL 16
    - Subnet group in the data subnets, parameter group, customer-managed KMS key
      for storage, no public access, backups from `backup_retention_days`,
      `multi_az = (az_count == 2)`, storage from `storage_gb` with autoscaling to
      a ceiling, and `manage_master_user_password` so no password is in files.
    - Deletion protection and final snapshot as variables so sandbox teardown can
      destroy the instance.
    - _Requirements: 1.6, 4.5_
  - [ ] 6.2 Implement the database security group
    - Accept PostgreSQL only from the compute tasks' security group.
    - _Requirements: 4.5_

- [ ] 7. Build the compute module
  - [ ] 7.1 Implement ECS Fargate and the task definition
    - Cluster with Container Insights, task definition sized by `task_size`,
      service in private subnets, placement driven by `az_count`, and the
      container image as an input variable with no account-specific URL.
    - _Requirements: 1.5, 3.3_
  - [ ] 7.2 Implement the ALB and auto scaling
    - Public ALB with a target group and listener, security groups limiting task
      ingress to the ALB, drop-invalid-headers on, and Application Auto Scaling
      between `min_tasks` and `max_tasks` on CPU.
    - Apply the HTTPS decision from the open questions once resolved; until then
      implement the HTTP default with an optional `certificate_arn` input.
    - _Requirements: 1.5, 4.5_

- [ ] 8. Write the root project templates
  - [ ] 8.1 Create the root templates
    - `main.tf.tmpl`, `variables.tf.tmpl`, `outputs.tf.tmpl`,
      `terraform.tfvars.example.tmpl`, and `README.md.tmpl`. The root declares
      Terraform `>= 1.10.0`, the pinned provider, and the S3 backend with
      `use_lockfile = true` and no bucket, key, or account values.
    - _Requirements: 3.2, 3.4_
  - [ ] 8.2 Add a reference render helper for tests
    - A minimal, test-only helper that fills the root templates from a parameter
      set so module validation can run before the real renderer exists. The real
      renderer is built in the generation spec and must reproduce its output.
    - _Requirements: 3.1, 3.2_

- [ ] 9. Create the resource inventory and sandbox policy
  - [ ] 9.1 Write `inventory.json`
    - List every resource type per module with its graph node type and pricing
      hint, as in `design.md`.
    - _Requirements: 1.1, 5.4_
  - [ ] 9.2 Generate `sandbox-policy.json`
    - A script that derives the least-privilege cross-account policy from the
      inventory, scoped by resource patterns and the `lusiform-managed` tag where
      supported.
    - _Requirements: 5.4_
  - [ ] 9.3 Write inventory and policy tests
    - Every resource type in the modules appears in the inventory and vice versa;
      the policy covers exactly that set and grants nothing else; no wildcard
      action.
    - _Requirements: 5.4_

- [ ] 10. Build the validation fixtures and tests
  - [ ] 10.1 Create parameter fixtures
    - Parameter sets: minimum, default, maximum, `az_count` 1, `az_count` 2.
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 10.2 Run the four validators against every fixture
    - Render each set and run `terraform fmt -check`, `terraform init
      -backend=false` plus `validate`, `tflint`, and `checkov`. Assert all pass
      and zero high-severity findings, using the severity map decided in the
      validation spec (record any assumption in the test).
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 10.3 Add the insecure fixture
    - A project with unencrypted RDS, a public database, and a wildcard IAM policy
      that must fail Checkov; assert it fails.
    - _Requirements: 4.6_
  - [ ] 10.4 Add the credential and account-ID scan
    - Scan all rendered output for access-key patterns, 12-digit account IDs, and
      ARNs containing an account; fail on any hit. Add a note-injection test that
      confirms free-text notes never reach resource names or file names.
    - _Requirements: 3.3, 3.5_
  - [ ] 10.5 Add determinism and golden tests
    - Render each fixture twice and compare hashes; compare to stored golden
      output; fail on any difference.
    - _Requirements: 3.1_

- [ ] 11. Add versioning and publication guards
  - [ ] 11.1 Record file hashes for published versions
    - A manifest of file hashes per version; a test fails if a published
      version's files change.
    - _Requirements: 5.1, 5.2_
  - [ ] 11.2 Add the review gate
    - A check that blocks setting `status` to `published` unless
      `review.reviewed_by` and `review.reviewed_at` are set; wire it into CI and
      the publish step.
    - _Requirements: 6.1, 6.3_
  - [ ] 11.3 Add the publish helper
    - A script that, given a version directory, validates it and produces the
      values for a `template_versions` row. It does not write to the database;
      the operator route in the admin spec does.
    - _Requirements: 5.3_

- [ ] 12. Expert review and release
  - [ ] 12.1 Prepare the review packet
    - Assemble the module set, parameter bounds, security defaults, sandbox
      policy, and the open questions (HTTPS, NAT per AZ, KMS keys) for the
      AWS-experienced reviewer.
    - _Requirements: 6.2_
  - [ ] 12.2 Resolve open questions and record the review
    - Fold in the reviewer's decisions, update the modules and tests, and record
      the review in `template.json`. Keep the version `draft` until this is done.
    - _Requirements: 6.1, 6.3_
  - [ ] 12.3 Publish the initial version
    - With the review recorded, mark `1.0.0` published and generate its file hash
      manifest.
    - _Requirements: 5.5, 6.1_

- [ ] 13. Final verification
  - [ ] 13.1 Run the full template suite
    - Schema, module validation, insecure fixture, credential scan, determinism,
      inventory, immutability, and review gate. All must pass.
    - _Requirements: all_
  - [ ] 13.2 Update steering with real commands
    - Record the exact template test and validation commands in
      `.kiro/steering/tech.md` and `terraform.md`.
    - _Requirements: NFR 3_
  - [ ] 13.3 Confirm the acceptance criteria
    - Walk requirements 1 to 6 and note which test or artifact proves each; flag
      anything not covered.
    - _Requirements: all_
