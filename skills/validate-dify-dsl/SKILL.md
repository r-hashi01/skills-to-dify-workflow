---
name: validate-dify-dsl
description: Validates the core nodes of a Dify DSL YAML file (workflow / chatflow export) against graphon, the graph engine schemas Dify itself uses. Reports invalid fields per node. Scope is core nodes only — triggers, knowledge-retrieval, agent, human-input, edges, and graph structure are not checked. Triggers on phrases like "validate this Dify DSL", "check this Dify YAML", "is this workflow importable", or after skills-to-dify-workflow assembles a draft.
---

# Dify DSL Validator (core nodes only)

Checks each core node's `data` in a Dify DSL YAML against graphon's pydantic models.

## Scope

| Checked | Not checked |
|---------|-------------|
| `data` of graphon core nodes: `start`, `end`, `answer`, `llm`, `tool`, `code`, `template-transform`, `if-else`, `question-classifier`, `parameter-extractor`, `document-extractor`, `list-operator`, `variable-aggregator`, `assigner`, `iteration`, `iteration-start`, `loop`, `loop-start`, `loop-end`, `http-request` | Dify-specific nodes (`trigger-*`, `knowledge-retrieval`, `agent`, `human-input`, `custom-note`, ...) — reported as `SKIPPED` |
| | Edges, sourceHandles, graph structure, app mode, top-level fields |
| | Secrets, external URLs, code safety |

Always state this scope when reporting a result. A passing result does not mean the file imports or runs correctly.

## Steps

1. Get the path of the DSL YAML. If the user pasted YAML instead, save it to a temporary file.
2. Run:
   ```bash
   uv run <this-skill-dir>/scripts/validate_dsl.py <file>.yml
   ```
   If `uv` is not installed, tell the user to install it (https://docs.astral.sh/uv/) and stop.
3. Interpret the exit code:
   - `0` — all core nodes valid
   - `1` — `FAIL` lines list each invalid node as `<node id> (<title>) [<type>]` followed by `field.path: message`
   - `2` — the file could not be read or has no `workflow.graph.nodes`
4. Report to the user: counts of valid / invalid / skipped nodes, each failure with its field path and the expected values from the message, and the list of skipped nodes that need manual review.
5. When called from `skills-to-dify-workflow`, fix the YAML and re-run until it exits `0`. Otherwise, propose fixes and apply them only if the user asks.

The validator only parses the YAML with `yaml.safe_load`; it never executes `code` nodes or contacts URLs in the file.
