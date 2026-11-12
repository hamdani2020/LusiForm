# tflint configuration for rendered startup-template projects.
#
# Used by the template tests and meant for the validator worker, so both judge a project by the
# same rules. Run it as:
#
#   tflint --config <this file> --chdir <project> --recursive --call-module-type=local
#
# `--recursive` matters: run from the project root without it, tflint does not inspect the
# resources inside the modules, so a violation in a module passes unnoticed.
#
# The AWS ruleset is preinstalled in the worker image (TFLINT_PLUGIN_DIR); tflint never
# downloads a plugin at run time. The version below must equal tools.tflint_ruleset_aws in
# template.json and the ARG in worker/Dockerfile; a test fails if they drift.
#
# Only findings at error level block a project. Warnings and notices are reported.

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
