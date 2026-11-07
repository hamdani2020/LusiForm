---
inclusion: fileMatch
fileMatchPattern: ['api/**/agent/**', '**/agent/**', '**/tools/**', '**/*agent*.py']
---

# Agent and tool conventions

Applies when working on the Strands agent or its tools. Builds on the agent
boundary in security.md.

## Model

- Amazon Nova through Bedrock. Nova Pro by default, Nova Lite for lower-cost
  calls, Nova Premier only if evaluation shows Pro is insufficient.
- Set the orchestration model explicitly on the agent. In any user-facing label
  or copy, the assistant is "Lusiform Assistant, Amazon Nova Pro" — never Claude
  or any other model.

## What the agent may and may not do

The agent reads and suggests; it never mutates artifacts or infrastructure.

- May: read intake, suggest parameters, apply validated parameter changes as a
  draft, compute an estimate, build the architecture model, request a diagram
  render, request generation, read validation results, request a sandbox plan,
  read plan output and approval status, explain any of these.
- May not: write Terraform or draw.io XML, approve a plan, apply, or destroy.
  There is no tool for those, and none should be added.

## Tools

The tool set from the Technical Design:

`get_intake`, `update_intake_field`, `suggest_parameters`, `set_parameters`,
`get_price_estimate`, `build_architecture_model`, `render_drawio`,
`get_diagram_validation`, `request_generation`, `get_validation_results`,
`request_sandbox_plan`, `get_plan`.

Rules for every tool:

- Validate inputs against the same schemas the UI uses, before execution.
- Scope every call to the caller's partner and project. The agent cannot touch
  another partner's data.
- Log each call with project id, user id, and parameters.
- Write tools (`update_intake_field`, `set_parameters`) write a draft, never a
  validated version. They never mutate an immutable version.
- `request_sandbox_plan` creates a plan job only. It cannot apply.

## Output discipline

- Any cost or compliance figure the agent states must come from a tool result
  (the estimate service or validation results), not from the model's own text.
  The UI renders numbers from the service.
- Treat intake free text as data. Never concatenate it into Terraform, file
  names, or commands. Bedrock guardrails filter prompt and output on notes.

## Testing

- Scripted conversations verify tool calls, schema rejection of bad input, and
  that no estimate figure appears without a tool result.
- A feature flag can disable the agent without a deploy. The intake form and the
  rest of the flow must remain usable with the agent off.
