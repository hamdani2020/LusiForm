/** The eight pipeline stages, in order, with the names from product.md. */
export const STAGES = [
  { name: "Intake", description: "Structured questions about the workload" },
  { name: "Architecture", description: "Review and adjust template parameters" },
  { name: "Diagram", description: "draw.io diagram from the architecture graph" },
  { name: "Estimate", description: "Cost from the AWS Pricing API, editable assumptions" },
  { name: "Terraform", description: "Readable, downloadable project" },
  { name: "Validation", description: "terraform fmt, validate, tflint, Checkov" },
  { name: "Sandbox", description: "Plan, named approval, apply, teardown" },
  { name: "Handoff", description: "Download the package" },
] as const;
