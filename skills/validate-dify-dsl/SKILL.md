---
name: validate-dify-dsl
description: Validates the core nodes of a Dify DSL YAML file (workflow / chatflow export) against graphon, the graph engine schemas Dify itself uses, and detects legacy shapes from older Dify versions. With --fix, upgrades legacy shapes to the current DSL (0.7.0) and writes a fixed copy. Scope is core nodes only — triggers, knowledge-retrieval, agent, human-input, edges, and graph structure are not schema-checked. Triggers on phrases like "validate this Dify DSL", "check this Dify YAML", "is this workflow importable", "upgrade this old Dify DSL", or after skills-to-dify-workflow assembles a draft.
---

# Dify DSL Validator (core nodes only)

Checks each core node's `data` in a Dify DSL YAML against graphon's pydantic models, and reports shapes from older Dify versions. `--fix` upgrades those shapes.

## Scope

| Checked | Not checked |
|---------|-------------|
| `data` of graphon core nodes: `start`, `end`, `answer`, `llm`, `tool`, `code`, `template-transform`, `if-else`, `question-classifier`, `parameter-extractor`, `document-extractor`, `list-operator`, `variable-aggregator`, `assigner` (v1 and v2), `iteration`, `iteration-start`, `loop`, `loop-start`, `loop-end`, `http-request` | Dify-specific nodes (`trigger-*`, `knowledge-retrieval`, `agent`, `human-input`, `custom-note`, ...) — reported as `SKIPPED` |
| Legacy shapes from older Dify versions (see below) | Edges, sourceHandles, graph structure, app mode, top-level fields |
| | Secrets, external URLs, code safety |

Always state this scope when reporting a result. A passing result does not mean the file imports or runs correctly.

### Legacy shapes

| Severity | Shape | `--fix` result |
|----------|-------|----------------|
| **Breaks** in current Dify | node type `variable-assigner` (old aggregator name; no runtime class) | `variable-aggregator` |
| **Breaks** | `assigner` with `items` but no `version: '2'` (parsed as v1, fails) | `version: '2'` |
| Tolerated, normalized only when the editor saves | if-else top-level `conditions`; http body `data` as a string; http without `retry_config`; parameter-extractor types `bool` / `select`; end `value_type: Array[...]`; tool node without `tool_node_version`; iteration / loop without a start child node; edges without handles; DSL `version` older than 0.7.0 | Same normalization Dify's editor applies |

Warnings only (cannot be fixed in the file): missing plugin `dependencies` (self-hosted Dify without the marketplace will not prompt to install them), and `knowledge-retrieval` dataset IDs (they must exist in the target workspace; IDs from another instance are silently dropped).

Invalid data that is not a legacy shape (e.g. an unknown start variable type) is reported as `FAIL` and never auto-fixed: the right value needs a human decision.

## Steps

1. Get the path of the DSL YAML. If the user pasted YAML instead, save it to a temporary file.
2. Run:
   ```bash
   uv run <this-skill-dir>/scripts/validate_dsl.py <file>.yml           # validate + report legacy shapes
   uv run <this-skill-dir>/scripts/validate_dsl.py <file>.yml --fix     # upgrade, write <file>.fixed.yml, validate it
   ```
   Use `--fix` only when the user asked for it (e.g. passed `--fix`, or said "fix" / "upgrade"). `--fix` never overwrites the input; it writes `<name>.fixed.yml` unless `-o <path>` is given. Pass the input path to `-o` only if the user explicitly asks to overwrite.
   If `uv` is not installed, tell the user to install it (https://docs.astral.sh/uv/) and stop.
3. Interpret the output and exit code:
   - `LEGACY (breaks …)` / `LEGACY (tolerated …)` — shapes `--fix` would change; `FIXED` — what `--fix` changed
   - `WARN` — issues the file cannot fix
   - `FAIL` — invalid node as `<node id> (<title>) [<type>]` followed by `field.path: message`
   - exit `0` — core nodes valid and nothing breaking left; `1` — `FAIL`s or breaking legacy shapes; `2` — the file could not be read or has no `workflow.graph.nodes`
4. Report to the user: counts of valid / invalid / skipped nodes, each failure with its field path and the expected values from the message, legacy shapes (and whether they break), warnings, and the skipped nodes that need manual review. If breaking legacy shapes were found without `--fix`, offer to run it.
5. When called from `skills-to-dify-workflow`, fix the YAML and re-run until it exits `0`. Otherwise, propose fixes for `FAIL`s and apply them only if the user asks.

The validator only parses the YAML with `yaml.safe_load`; it never executes `code` nodes or contacts URLs in the file.
