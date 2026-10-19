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
/plugin install skills-to-dify-workflow@r-hashi01
```

## Usage

Once installed, trigger the skill by saying:

- "Convert this skill to Dify"
- "Visualize this skill as a workflow"
- "Show this skill in Dify"

The skill will walk you through the conversion interactively, including a security review of the source skill and confirming your Dify model provider/name before generating the YAML.

### Converting a Dify workflow into a skill

The `dify-to-skill` skill goes the other way: it turns a Dify `workflow` / `advanced-chat` app into a Claude Code skill folder.

- `/skills-to-dify-workflow:dify-to-skill app.yml`
- or say "Convert the Dify app <name> to a skill" — with [difyctl](https://github.com/langgenius/dify/tree/main/cli) logged in, it exports the app for you

Code nodes become runnable scripts, prompts become skill steps, branches and loops become conditional instructions. Because converted code runs on your machine instead of Dify's sandbox, a security review is mandatory. The draft is written to `./<name>/` and checked before you choose where to install it (`~/.claude/skills/` or the project's `.claude/skills/`). Requires [uv](https://docs.astral.sh/uv/).

### Explaining a Dify workflow

The `explain-dify-dsl` skill helps you understand an existing app, e.g. one you are taking over:

- `/skills-to-dify-workflow:explain-dify-dsl app.yml`
- or say "Explain the Dify app <name>"

You get one self-contained HTML file laid out like DeepWiki: concept pages (overview, how it works with concrete branch conditions, one page per stage explaining its prompts, things to watch) with inline diagrams and links to node pages, a clickable flow map, and a generated reference page for every node (inputs and settings with their sources, branches, where outputs are used, full prompt / code). Requires [uv](https://docs.astral.sh/uv/).

### Validating a Dify DSL file

The `validate-dify-dsl` skill checks any Dify DSL YAML (generated or exported from Dify):

- `/skills-to-dify-workflow:validate-dify-dsl app.yml`
- `/skills-to-dify-workflow:validate-dify-dsl app.yml --fix` — also upgrade shapes from older Dify versions (writes `app.fixed.yml`)
- or say "Validate this Dify DSL"

It validates **core nodes only** against [graphon](https://pypi.org/project/graphon/), the schemas Dify itself uses. Triggers, knowledge-retrieval, agent, human-input, edges and graph structure are not validated. It also detects legacy shapes that break in current Dify (e.g. the old `variable-assigner` node type) or that only the editor normalizes, and `--fix` upgrades them the same way Dify's editor does. Requires [uv](https://docs.astral.sh/uv/); the conversion skill runs it automatically when uv is available.

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
│   ├── dify-to-skill/
│   │   ├── SKILL.md                         # Reverse conversion: Dify DSL → skill
│   │   ├── references/
│   │   │   └── node-to-skill-mapping.md     # Node → skill element rules
│   │   └── scripts/
│   │       ├── analyze_dsl.py               # DSL analysis + code extraction
│   │       └── check_skill.py               # Generated skill checks
│   ├── explain-dify-dsl/
│   │   ├── SKILL.md                         # Explanation + diagram
│   │   └── scripts/
│   │       └── render_preview.py            # Graph JSON → HTML flow diagram
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
- Optional: [uv](https://docs.astral.sh/uv/) for the `dify-to-skill`, `explain-dify-dsl` and `validate-dify-dsl` skills
- Optional: [difyctl](https://github.com/langgenius/dify/tree/main/cli) to pull apps directly from a Dify server

## License

[Apache 2.0](LICENSE)
