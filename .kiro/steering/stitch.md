# Stitch (UI designs)

Stitch holds the Lusiform screen designs (project `18075726235522465175`). Anything that
touches it goes through the Stitch MCP server and nothing else.

## Rules

- Use only the Stitch MCP tools for every Stitch task: listing or reading projects and
  screens, creating or editing screens, generating variants, design systems, uploading
  or downloading files, and anything else Stitch offers.
- Never use `curl`, `wget`, `web_fetch`, or any other HTTP client against Stitch URLs,
  including the `downloadUrl` values in tool results. They need credentials the shell
  does not have and return 401. If a file cannot be read through an MCP tool, say so
  and ask the user instead of working around it.
- Do not run, proxy, or reach the Stitch MCP server through Docker or a container, and do
  not add it to `compose.yaml`. Kiro connects to it from the host using
  `.kiro/settings/mcp.json` (see `docker.md`).
- Call the tools through `tool_call` after loading each one with `load_resource`
  (`tool::stitch::<tool_name>`). Do not edit `.kiro/settings/mcp.json` unless asked.

## Working with screens

- Read a screen with `get_screen` before editing it, and edit with `edit_screens`.
  Say in the prompt what must stay unchanged, and list only the changes wanted.
- After an edit, report what Stitch says it changed. If the result shows changes that
  were not requested, tell the user.
- The PRD and Technical Design win over any screen (see `product.md`). When a design
  decision changes the product, update the screen to match it, not the other way round.
- Keep `templates/tests/data/architecture_stage_values.json` and `schema.json` in step
  with the Architecture-stage screen; `test_schema.py` fails if they disagree.
