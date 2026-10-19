# Dify Node → Skill Mapping

How each Dify node becomes part of a Claude Code skill. For what each node's fields mean, see the DSL reference of the sibling skill: [`../../skills-to-dify-workflow/references/dify-node-types.md`](../../skills-to-dify-workflow/references/dify-node-types.md).

The portability tag printed by `analyze_dsl.py` is shown in brackets.

---

## Writing the generated SKILL.md

```markdown
---
name: <kebab-case-ascii-name>
description: <What it does, in third person>. Converted from the Dify app "<app name>". Use when <trigger phrases / situations>.
---

# <Title>

<One paragraph: purpose and expected result.>

## Inputs
## Requirements        (only if any: env vars, CLIs, connected tools, Python packages)
## Steps
## Output
```

- **Steps follow the analyzer's execution order.** Number them. Write branches as "If …: go to Step N. Otherwise: …". Nest container bodies (iteration / loop) as sub-steps.
- **Replace every `{{#node.field#}}`** with a plain reference to where the value came from: "the category from Step 4", "the user's request". No Dify template syntax may remain in SKILL.md or references/.
- **Keep prompts verbatim** (they encode the domain logic) and in their original language. Only replace variable placeholders with descriptive markers such as `<inquiry text from Inputs>`.
- **Move long content out.** A prompt over ~40 lines, a template, or reference text goes to `references/<slug>.md` or `assets/<slug>`, linked from the step: "Follow [references/triage-prompt.md](references/triage-prompt.md)".
- **Drop Dify-only settings**: model provider/name, temperature, retry intervals, node positions, UI flags. Keep behavior that matters: "respond with strict JSON", "retry up to 3 times".
- **Keep SKILL.md under 500 lines.**
- `sys.query` = the user's message; `sys.files` = files the user provided; other `sys.*` values (user_id, app_id, …) are dropped.

---

## Node mapping

| Dify node | Becomes |
|-----------|---------|
| `start` [native] | **Inputs** section: one bullet per variable (name, meaning, required). Say how to get missing ones: ask the user. `file` / `file-list` → ask for file paths. `select` → list the allowed options. |
| `end` [native] | **Output** section: the final summary must include each output variable. |
| `answer` [native] | A reply to the user at that point. Multiple answers → intermediate messages. |
| `llm` [native] | A step Claude performs. System prompt = instructions for the step; user prompt = what to apply them to. `structured_output` → "Produce JSON with exactly these fields: …". `context` → uses the result of the knowledge step. `memory` → nothing (the conversation already holds history). |
| `parameter-extractor` [native] | "Extract these fields from …" with each parameter's name, type, description, required. |
| `question-classifier` [native] | "Classify … into exactly one of: A (description), B (…)", then one branch per class. |
| `if-else` [native] | Conditional step. Write conditions in words (`contains 'auto'` → "mentions auto"). ELIF cases in order, then ELSE. |
| `iteration` [native] | "For each item in …:" with the body as sub-steps; collect the results. Parallel mode may note that subagents can process items concurrently when there are many. |
| `loop` [native] | "Repeat (at most N times) until …:" with loop variables as tracked values. `loop-end` → "stop repeating". |
| `template-transform` [native] | Short: fill the text inline. Long: `assets/<slug>.md` with placeholders, and "Fill assets/<slug>.md". Convert Jinja2 `{{ var }}` names to descriptive placeholders. |
| `variable-aggregator` [native] | "Use whichever branch produced …". Usually disappears into the prose. |
| `assigner` + conversation variables [native] | "Keep track of …" / "Update … to …". In a chatflow, state that persists across turns of the conversation. |
| `list-operator` [native] | Describe the filter / sort / limit in words. |
| `document-extractor` [native] | "Read the file with the Read tool." For formats Read cannot open, name the conversion needed (e.g. `pandoc`). |
| `human-input` [native] | Ask the user with AskUserQuestion: form fields become questions, `user_actions` become options, each action's branch follows. Timeout is dropped. |
| `agent` [native] | A step where Claude works autonomously with the tools the agent had (map each tool as below), keeping its instruction and iteration limit. |
| `code` [script] | `scripts/<slug>.py` / `.js` from `--extract-code` (original code + stdin/stdout JSON harness). Step: "Run `python3 scripts/<slug>.py` with a JSON object of `{key: value}` on stdin; it prints a JSON object with …". Non-stdlib imports go to **Requirements**. Trivial code (parsing the previous LLM's JSON, joining strings) may be replaced by Claude doing it, only if the user agrees in the plan. |
| `http-request` [script] | GET without credentials → WebFetch. Anything with a body or credentials → a small `scripts/<slug>.py` using `urllib.request` that reads values as JSON on stdin and secrets from environment variables. Do not build `curl` commands by interpolating user text into the shell. |
| `tool` [manual] | Pick the Claude Code equivalent **with the user**: web search (Tavily, Google, Bing, …) → WebSearch; page reading / scraping (Jina Reader, Firecrawl, …) → WebFetch; current time → `date`; services (Gmail, Slack, Notion, GitHub, …) → a connected MCP server or CLI the user confirms, else the service's HTTP API as a script, else a manual step for the user. Never invent MCP tool names. |
| `knowledge-retrieval` [manual] | The DSL contains only dataset IDs, not the documents. Ask the user: (a) put the documents into `references/knowledge/` and search them with Grep/Read; (b) keep querying the Dify knowledge base through its Knowledge API (script + `DIFY_DATASET_API_KEY`); or (c) drop the step. |
| `trigger-schedule` [manual] | The skill is invoked manually. Tell the user to schedule it with `/schedule` using the original cron / frequency and timezone. |
| `trigger-webhook`, `trigger-plugin` [unsupported] | Cannot run as a skill. The skill takes the trigger's payload fields as **Inputs**; note in the report that an external caller must invoke it. |
| `iteration-start`, `loop-start`, `custom-note` | Not steps. Useful note text may go into the skill's introduction. |
| `datasource`, `knowledge-index` [unsupported] | RAG pipeline only. Stop and tell the user the app cannot be converted. |

### Node-level settings

| Setting | Becomes |
|---------|---------|
| `retry_config.retry_enabled` | "If it fails, retry up to N times." |
| `error_strategy: fail-branch` | "If this step fails: …" (the fail branch's steps). |
| `error_strategy: default-value` | "If this step fails, use … instead." |

### Environment variables

- `secret` → listed under **Requirements** as an environment variable the user must export; scripts read it from `os.environ`. Never write a value.
- `string` / `number` → configuration. Ask the user whether to keep each exported value (it may be an internal ID); keep kept values in a **Configuration** list in SKILL.md, not scattered through steps.

### App mode

| Mode | Skill shape |
|------|-------------|
| `workflow` | Runs once from inputs to the **Output** section. |
| `advanced-chat` | Conversational: inputs come from the user's messages; `answer` nodes are replies; conversation variables persist across turns. |
| `chat`, `agent-chat`, `completion` | No workflow graph. Not supported by this skill. |
