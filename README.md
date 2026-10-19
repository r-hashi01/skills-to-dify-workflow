# skills-to-dify-workflow

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin that converts skill definitions into [Dify](https://dify.ai/)-importable workflow DSL (YAML files). It also generates a React Artifact for visual preview before export.

## What It Does

Skill logic is written as Markdown prose, making parallel execution, loops, conditionals, and LLM usage invisible to non-engineers. This plugin translates that prose into a Dify workflow diagram, turning personal automation into a shareable organizational asset.

Given a Claude Code skill folder, it:

1. **Reads** the entire skill directory — `SKILL.md`, `scripts/`, `references/`, `assets/`
2. **Reviews** for security risks — dangerous scripts, prompt injection, hardcoded secrets
3. **Analyzes** the processing flow — extracts LLM usage, tool calls, branches, loops, and parallelism
4. **Determines** the Dify mode — `workflow` (single-shot) or `advanced-chat` (conversational)
5. **Builds** a Dify DSL YAML following the exact structure that Dify expects, and validates core nodes against Dify's own [graphon](https://pypi.org/project/graphon/) schemas
6. **Previews** as a React Artifact — color-coded nodes, click-to-inspect, exportable
7. **Exports** a `.yml` file ready to import via Dify's "Import DSL File"

## Installation

```bash
# Add the marketplace
/plugin marketplace add r-hashi01/skills-to-dify-workflow

# Install the plugin
/plugin install skills-to-dify-workflow@skills-to-dify-workflow
```

## Usage

Once installed, trigger the skill by saying:

- "Convert this skill to Dify"
- "Visualize this skill as a workflow"
- "Show this skill in Dify"

The skill will walk you through the conversion interactively, including a security review of the source skill and confirming your Dify model provider/name before generating the YAML.

### Validating a Dify DSL file

The `validate-dify-dsl` skill checks any Dify DSL YAML (generated or exported from Dify):

- `/skills-to-dify-workflow:validate-dify-dsl app.yml`
- or say "Validate this Dify DSL"

It validates **core nodes only** against [graphon](https://pypi.org/project/graphon/), the schemas Dify itself uses. Triggers, knowledge-retrieval, agent, human-input, edges and graph structure are not validated. Requires [uv](https://docs.astral.sh/uv/); the conversion skill runs it automatically when uv is available.

## Plugin Structure

```
skills-to-dify-workflow/
├── .claude-plugin/
│   └── plugin.json                          # Plugin manifest
├── marketplace.json                         # Marketplace definition
├── skills/
│   ├── skills-to-dify-workflow/
│   │   ├── SKILL.md                         # Conversion skill
│   │   └── references/
│   │       └── dify-node-types.md           # Dify DSL schema reference
│   └── validate-dify-dsl/
│       ├── SKILL.md                         # Validation skill (core nodes only)
│       └── scripts/
│           └── validate_dsl.py              # graphon-based validator (uv run)
├── CLAUDE.md                                # Dev guidance for contributors
├── LICENSE                                  # Apache 2.0
└── README.md
```

## Node Type Mapping

| Pattern in Skill             | Dify Node Type | Artifact Color |
|-----------------------------|----------------|----------------|
| Claude decides / generates   | `llm`, `agent`, `parameter-extractor` | Purple |
| Script / API / file ops      | `code`, `tool`, `http-request`, `document-extractor`, `knowledge-retrieval` | Blue |
| Branching / routing          | `if-else`, `question-classifier` | Yellow |
| Loop over list / while loop  | `iteration`, `loop` | Orange    |
| Text formatting / list ops   | `template-transform`, `variable-aggregator`, `assigner`, `list-operator` | Green |
| Ask the user / approval      | `human-input`  | Pink           |
| Input / Output               | `start`, `trigger-*` / `end`, `answer` | Gray |
| Steps Dify can't run         | `custom-note`  | Note           |

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- A Dify instance to import the generated YAML
- Optional: [uv](https://docs.astral.sh/uv/) for the `validate-dify-dsl` skill

## License

[Apache 2.0](LICENSE)
