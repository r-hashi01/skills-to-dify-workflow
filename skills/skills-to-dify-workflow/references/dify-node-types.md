# Dify DSL Reference (YAML Format)

Follow this reference when generating export YAML. Node schemas come from two sources:

- **Core nodes** — the [`graphon`](https://pypi.org/project/graphon/) graph engine package that Dify pins in `api/pyproject.toml`. Types are listed in `graphon/enums.py` (`BuiltinNodeTypes`) and schemas in `graphon/nodes/<node>/entities.py`. Shared fields come from `graphon/entities/base_node_data.py`.
- **Dify-specific nodes** — `api/core/workflow/nodes/<node>/entities.py` in the Dify repository (triggers, knowledge, agent, human-input form schema), plus UI-only nodes from `web/app/components/workflow/`.

When the two disagree, graphon wins for core nodes.

---

## Overall File Structure

```yaml
app:
  description: ''
  icon: 🤖
  icon_type: emoji
  icon_background: '#FFEAD5'
  mode: workflow        # workflow | advanced-chat
  name: App Name
  use_icon_as_answer_icon: false
dependencies: []        # Plugins used (see "dependencies" below)
kind: app
version: 0.7.0
workflow:
  conversation_variables: []   # Variables persisted across conversation turns (advanced-chat only)
  environment_variables: []
  features: { ... }            # File upload settings, etc. (mostly defaults)
  graph:
    edges: [ ... ]
    nodes: [ ... ]
  viewport:
    x: 0
    y: 0
    zoom: 0.8
  rag_pipeline_variables: []
```

Dify instances whose own DSL version is older than the file's ask the user to confirm before importing; the import still works.

### dependencies

List every marketplace plugin the workflow uses (model providers, tools, agent strategies, triggers) so Dify prompts the user to install them on import:

```yaml
dependencies:
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: langgenius/tavily:0.1.0@<hash>
```

Do not invent the `@<hash>` part. If the exact identifier is unknown, leave `dependencies: []` and tell the user which plugins to install.

---

## Common Node Structure

```yaml
- data:
    desc: ''
    selected: false
    title: Node Title
    type: node_type
    # Type-specific fields
  height: 90
  id: 'unique_timestamp_id'
  position:
    x: 300.0
    y: 400.0
  positionAbsolute:
    x: 300.0
    y: 400.0
  selected: false
  sourcePosition: right
  targetPosition: left
  type: custom          # custom-note for notes; see container internals for start nodes
  width: 244
```

`data` fields shared by every node (graphon `BaseNodeData`): `type`, `title`, `desc`, `version` (default `'1'`), `error_strategy`, `default_value`, `retry_config`. Unknown extra keys are tolerated.

### Error handling (optional, any executable node)

```yaml
retry_config:
  retry_enabled: true
  max_retries: 3
  retry_interval: 1000          # milliseconds
error_strategy: fail-branch     # fail-branch | default-value (omit = stop workflow on error)
default_value:                  # Only with error_strategy: default-value
- key: text                     # Output field name
  type: string                  # string | number | object | array[string] | array[number] | array[object] | array[file]
  value: 'fallback text'
```

With `error_strategy: fail-branch`, the node gets two outgoing handles: `sourceHandle: source` (success) and `sourceHandle: fail-branch` (failure). The failure path can read `error_message` and `error_type` from the node.

### Nodes inside a container (iteration / loop)

```yaml
  data:
    isInIteration: true                # iteration children
    iteration_id: 'parent_iteration_node_id'
    # or, for loop children:
    # isInLoop: true
    # loop_id: 'parent_loop_node_id'
  parentId: 'parent_node_id'
  zIndex: 1002
```

The engine selects a container's children by `data.iteration_id` / `data.loop_id`, so these are required, not cosmetic. `position` of a child node is relative to the container's top-left corner.

---

## Conditions (shared by if-else and loop)

graphon `utils/condition/entities.py`:

```yaml
- id: uuid-here
  variable_selector: [node_id, field_name]
  comparison_operator: contains
  value: 'urgent'            # string, list of strings, or bool
  varType: string            # UI hint: string | number | boolean | object | array[...] | file
  sub_variable_condition:    # Optional: conditions on file attributes (array[file])
    logical_operator: and
    conditions:
    - key: extension
      comparison_operator: is
      value: '.pdf'
```

Comparison operators (exact strings, note the spaces):
- string / array: `contains` `not contains` `start with` `end with` `is` `is not` `empty` `not empty` `in` `not in` `all of`
- number: `=` `≠` `>` `<` `≥` `≤`
- null checks: `null` `not null`
- file: `exists` `not exists`

---

## Core Nodes (graphon)

### start (Entry Point)
`graphon/nodes/start` + `graphon/variables/input_entities.py`
```yaml
type: start
variables:
- label: Input Label
  max_length: 48
  options: []
  required: true
  type: paragraph     # text-input | paragraph | select | number | checkbox | file | file-list | json_object
  variable: variable_name
```

File inputs add:
```yaml
  type: file          # file (single) | file-list (multiple)
  allowed_file_types: [document]       # image | document | audio | video | custom
  allowed_file_extensions: []          # Required when allowed_file_types includes custom (e.g. ['.csv'])
  allowed_file_upload_methods: [local_file, remote_url]
  max_length: 5                        # file-list only: max file count
```

`select` uses `options: ['A', 'B']`. `json_object` may carry `json_schema` (a JSON Schema object).

### end (Workflow Termination)
`workflow` mode only (`advanced-chat` uses `answer`).
```yaml
type: end
outputs:
- value_selector:
  - node_id
  - field
  value_type: string     # optional, default any
  variable: output_text
```

### answer (Final Output, advanced-chat)
```yaml
type: answer
answer: '{{#node_id.text#}}'
variables: []
```

### llm (LLM Invocation)
```yaml
type: llm
model:
  completion_params:
    temperature: 0.7
    # response_format varies by provider (see note below)
  mode: chat
  name: claude-sonnet-4-5          # Use model name installed in the user's Dify environment
  provider: langgenius/anthropic/anthropic
prompt_template:
- id: uuid-here
  role: system
  text: 'System prompt'
- id: uuid-here
  role: user
  text: '{{#start.variable#}}'
variables: []
context:
  enabled: false
  variable_selector: []
vision:
  enabled: false
reasoning_format: tagged          # tagged (keep <think>) | separated (text + reasoning_content)
memory:                           # Only when using conversation history
  query_prompt_template: '{{#sys.query#}}'
  role_prefix:
    assistant: ''
    user: ''
  window:
    enabled: false
    size: 50
```

**Structured output** (JSON matching a schema; result in `structured_output`):
```yaml
structured_output_enabled: true
structured_output:
  schema:
    type: object
    properties:
      title: { type: string }
      tags: { type: array, items: { type: string } }
    required: [title]
    additionalProperties: false
```

**Context (RAG)**: set `context.enabled: true` and `variable_selector: [kr_node_id, result]`, then put `{{#context#}}` in the system prompt.

**Model name and provider notes**:
- `name` and `provider` depend on the model plugin installed in the user's Dify environment
- Available model names can be found at https://github.com/langgenius/dify-official-plugins under `models/<provider>/models/llm/` YAML filenames
- `completion_params` also vary by provider. For example, `response_format` is `json_object` for OpenAI and `JSON | XML` for Anthropic. Refer to each provider's `models/llm/<model>.yaml` `parameter_rules`
- When assembling YAML, confirm the model with the user and reference the relevant plugin definition for correct parameters

### tool (External Tool)
```yaml
type: tool
provider_id: langgenius/tavily/tavily
provider_name: langgenius/tavily/tavily
provider_type: builtin      # builtin | plugin | api | workflow | mcp | app | dataset-retrieval
tool_label: Tavily Search
tool_name: tavily_search
tool_configurations:        # Form-type settings (constants: str | int | float | bool | dict)
  search_depth: advanced
  max_results: 5
tool_parameters:            # LLM/user inputs
  query:
    type: mixed             # mixed (template string) | variable (selector list) | constant
    value: '{{#node_id.field#}}'
```

`provider_type: mcp` calls a tool on an MCP server registered in the workspace; `workflow` calls another published Dify workflow as a tool. Both depend on workspace state, so confirm the provider ID with the user.

### code (Python / JavaScript Execution)
```yaml
type: code
code_language: python3       # python3 | javascript
code: |
  def main(input_var: str) -> dict:
      return {"result": input_var}
outputs:
  result:
    children: null
    type: string             # string | number | boolean | object | array[string] | array[number] | array[boolean] | array[object]
variables:
- value_selector:
  - start_node_id
  - variable_name
  variable: input_var
```

JavaScript form: `function main({input_var}) { return { result: input_var } }`.

### template-transform (Jinja2 Template)
```yaml
type: template-transform
template: '{{ var1 }}/{{ var2 }} processing iteration'
variables:
- value_selector:
  - node_id
  - field
  variable: var1
```

### if-else (Conditional Branch)
```yaml
type: if-else
cases:
- case_id: 'true'                    # First case (IF)
  id: 'true'
  logical_operator: and              # and | or
  conditions: [ ... ]                # See "Conditions"
- case_id: case-uuid-2               # Additional cases = ELIF
  id: case-uuid-2
  logical_operator: or
  conditions: [ ... ]
```

Edge sourceHandle: each case's `case_id` (first case is usually `'true'`), and `'false'` for ELSE.

### question-classifier (Question Classification)
Uses an LLM to classify input into categories. Edge sourceHandle is the class `id`.
```yaml
type: question-classifier
query_variable_selector:
- start
- query
model:
  provider: langgenius/openai/openai
  name: gpt-4o-mini
  mode: chat
  completion_params: {}
classes:
- id: '1'
  name: 'Questions about pricing or billing'   # Category description shown to the LLM
  label: Pricing                               # Optional display label
- id: '2'
  name: 'Technical support requests'
instruction: ''
vision:
  enabled: false
```

### parameter-extractor (Parameter Extraction)
```yaml
type: parameter-extractor
query:
- start
- query
model:
  provider: langgenius/openai/openai
  name: gpt-4o-mini
  mode: chat
  completion_params: {}
parameters:
- name: city       # __reason and __is_success are reserved
  type: string     # string | number | boolean | array[string] | array[number] | array[boolean] | array[object]
  description: 'City name to extract'
  required: true
  options: []      # Optional enum choices for string
reasoning_mode: function_call   # function_call | prompt
instruction: ''
vision:
  enabled: false
```

### document-extractor (File Text Extraction)
Extracts text from file variables (PDF, DOCX, XLSX, CSV, TXT, MD, HTML, etc.).
```yaml
type: document-extractor
is_array_file: false   # UI flag: true when the input is a file-list
variable_selector:
- start
- file
```

### list-operator (List Operations)
Filters, sorts, slices, and extracts items from an array (including `array[file]`).
```yaml
type: list-operator
variable:
- node_id
- list_output
filter_by:
  enabled: true
  conditions:
  - key: name      # Sub-field for objects/files (name, type, extension, size, ...); '' for primitives
    comparison_operator: contains   # contains | not contains | start with | end with | is | is not | in | not in | empty | not empty | = | ≠ | < | > | ≥ | ≤
    value: 'keyword'
order_by:
  enabled: false
  key: ''
  value: asc      # asc | desc
limit:
  enabled: true
  size: 5
extract_by:
  enabled: false
  serial: '1'     # 1-based index
```

### variable-aggregator (Variable Merge)
```yaml
type: variable-aggregator
output_type: string
variables:
- - node_id_1
  - output
- - node_id_2
  - output
advanced_settings:          # Optional: multiple independent groups
  group_enabled: true
  groups:
  - group_name: summary
    output_type: string
    variables: [[node_id_1, text], [node_id_2, text]]
```

Outputs the first non-empty variable — use it after branches to join paths. `variable-assigner` is the legacy type name for this node; do not generate it.

### assigner (Variable Assignment)
```yaml
type: assigner
version: '2'
items:
- input_type: variable      # variable (value is a selector) | constant (value is a literal)
  operation: over-write
  value:
  - source_node_id
  - field_name
  variable_selector:
  - conversation            # conversation variable, or [loop_node_id, label] inside a loop
  - variable_name
```

Operations: `over-write` `clear` `set` (constant) / `append` `extend` `remove-first` `remove-last` (arrays) / `+=` `-=` `*=` `/=` (numbers).

### iteration (List Loop Processing)
```yaml
type: iteration
error_handle_mode: terminated    # terminated | continue-on-error | remove-abnormal-output
is_parallel: false
parallel_nums: 10                # >= 1
flatten_output: true             # Flatten when every element is itself a list
iterator_selector:
- code_node_id
- array_field
output_selector:
- inner_node_id
- output
output_type: array[string]
start_node_id: iteration_idstart  # iteration node's id + "start"
```
Node-level `height`/`width` must enclose all children (e.g. `height: 250`, `width: 900`).

First node inside iteration (iteration-start):
```yaml
- data:
    desc: ''
    isInIteration: true
    title: ''
    type: iteration-start
  draggable: false
  height: 48
  id: iteration_idstart            # iteration node's id + "start"
  parentId: iteration_node_id
  position:
    x: 24
    y: 68
  selectable: false
  type: custom-iteration-start
  width: 44
  zIndex: 1002
```

### loop (Conditional Loop)
Repeats internal nodes until a break condition is met or `loop_count` is reached (while-loop equivalent).
```yaml
type: loop
start_node_id: loop_idstart       # loop node's id + "start"
loop_count: 10                    # >= 1, max iterations
logical_operator: and             # and | or (for break_conditions)
break_conditions:                 # See "Conditions"
- id: cond-uuid
  variable_selector:
  - loop_node_id
  - counter
  comparison_operator: "≥"
  value: '5'
  varType: number
loop_variables:
- id: var-uuid
  label: counter                  # Referenced as [loop_node_id, counter]
  var_type: number                # string | number | boolean | object | array[string] | array[number] | array[boolean] | array[object]
  value_type: constant            # constant | variable
  value: 0                        # constant value, or a selector list when value_type: variable
```

First node inside loop (loop-start), mirrors iteration-start:
```yaml
- data:
    desc: ''
    isInLoop: true
    title: ''
    type: loop-start
  draggable: false
  height: 48
  id: loop_idstart
  parentId: loop_node_id
  position:
    x: 24
    y: 68
  selectable: false
  type: custom-loop-start
  width: 44
  zIndex: 1002
```

`loop-end` (optional, `type: custom`, data `type: loop-end`, no other fields) placed inside the loop exits immediately when reached, e.g. after an if-else branch. Update loop variables each round with an `assigner` inside the loop targeting `[loop_node_id, label]`.

### http-request (External API Call)
```yaml
type: http-request
method: post       # get | post | put | patch | delete | head | options
url: 'https://api.example.com/data'
headers: 'Content-Type: application/json'   # newline-separated "Key: Value"
params: ''                                  # newline-separated "key: value"
body:
  type: json       # none | form-data | x-www-form-urlencoded | raw-text | json | binary
  data:
  - type: text     # text | file (file only for form-data / binary)
    key: ''        # field name for form-data / x-www-form-urlencoded
    value: '{"key":"{{#node_id.value#}}"}'
authorization:
  type: no-auth    # no-auth | api-key
  config: null     # api-key: {type: bearer | basic | custom, api_key: '{{#env.API_KEY#}}', header: ''}
timeout:
  connect: 10
  read: 60
  write: 20
ssl_verify: true
```

Never put a literal key in `api_key`; reference an `environment_variables` entry with `value: ''` (value_type `secret`) and let the user fill it after import.

---

## Dify-Specific Nodes

These node types are executed by Dify itself rather than graphon. (`agent`, `human-input`, `knowledge-retrieval` and `datasource` are named in graphon's `BuiltinNodeTypes`, but their schemas live in Dify.)

### knowledge-retrieval (Knowledge Base Search)
`api/core/workflow/nodes/knowledge_retrieval`. RAG search; requires existing dataset IDs in the user's workspace.
```yaml
type: knowledge-retrieval
query_variable_selector:
- start
- query
dataset_ids:
- dataset-uuid
retrieval_mode: multiple   # single | multiple
multiple_retrieval_config:
  top_k: 4
  score_threshold: null
  reranking_enable: false
single_retrieval_config:   # Only when retrieval_mode: single
  model: { provider: ..., name: ..., mode: chat, completion_params: {} }
metadata_filtering_mode: disabled  # disabled | automatic | manual
```

### agent (Agent)
`api/core/workflow/nodes/agent`. Autonomously calls tools using an agent strategy plugin (e.g. `langgenius/agent`, which must be installed).
```yaml
type: agent
agent_strategy_provider_name: langgenius/agent/agent
agent_strategy_name: function_calling     # function_calling | ReAct
agent_strategy_label: FunctionCalling
plugin_unique_identifier: langgenius/agent:<version>@<hash>   # omit if unknown
tool_node_version: '2'
agent_parameters:
  model:
    type: constant
    value:
      provider: langgenius/anthropic/anthropic
      model: claude-sonnet-4-5
      model_type: llm
      mode: chat
      completion_params: {}
      type: model-selector
  instruction:
    type: constant
    value: 'You are a research assistant...'
  query:
    type: constant          # mixed template string also allowed
    value: '{{#start.query#}}'
  tools:
    type: constant
    value: []               # Tool selector objects; leave empty and tell the user to add tools in the UI
  maximum_iterations:
    type: constant
    value: 5
memory:                     # advanced-chat only
  window:
    enabled: false
    size: 50
```

The newer "Dify Agent" node (`api/core/workflow/nodes/agent_v2`: `version: '2'`, `agent_node_kind: dify_agent`) binds to a workspace-owned agent record and cannot be portably exported. Do not generate it.

### human-input (Awaiting Human Input)
graphon keeps only the pause/resume contract; the form schema is in `api/core/workflow/nodes/human_input/entities.py` and delivery in `api/core/workflow/human_input_adapter.py`. Pauses the workflow until a person submits a form or clicks an action button. Use this to convert "confirm with the user" / "ask for approval" steps.
```yaml
type: human-input
delivery_methods:
- id: uuid-here
  type: webapp              # webapp | email
  enabled: true
  config: {}
form_content: |
  Please review the draft:

  {{#llm_node.text#}}

  Feedback: {{#$output.feedback#}}
inputs:
- type: paragraph           # paragraph | select | file | file-list
  output_variable_name: feedback
  default: null             # or {type: constant, value: '...'} / {type: variable, selector: [node, field]}
- type: select
  output_variable_name: priority
  option_source:
    type: constant          # constant | variable
    value: [high, low]
user_actions:
- id: approve               # identifier: letters, digits, underscore; max 20 chars
  title: 'Approve'
  button_style: primary     # primary | default | accent | ghost
- id: revise
  title: 'Request changes'
  button_style: default
timeout: 36
timeout_unit: hour          # hour | day
```

Placeholders `{{#$output.<name>#}}` in `form_content` render the input fields. Email delivery needs workspace recipients; default to `webapp` only.

### trigger-webhook / trigger-schedule / trigger-plugin (External Triggers)
`api/core/workflow/nodes/trigger_*`. Start nodes that launch the workflow from outside. `workflow` mode only. **A workflow uses either `start` or trigger node(s), never both.** Multiple triggers may coexist.

```yaml
# Webhook — Dify generates the URL after import
type: trigger-webhook
method: post                     # get | post | put | patch | delete | head
content_type: application/json   # application/json | multipart/form-data | application/x-www-form-urlencoded | text/plain | application/octet-stream
headers:
- name: X-Request-Id
  type: string                   # string only
  required: false
params:                          # Query parameters
- name: lang
  type: string                   # string | number | boolean
  required: false
body:
- name: message
  type: string                   # string | number | boolean | object | array[string] | array[number] | array[boolean] | array[object] | file
  required: true
status_code: 200
response_body: ''
timeout: 30
```

```yaml
# Schedule
type: trigger-schedule
mode: visual                     # visual | cron
frequency: daily                 # hourly | daily | weekly | monthly (visual mode)
visual_config:
  time: '9:00 AM'                # daily / weekly / monthly
  on_minute: 0                   # hourly
  weekdays: [mon, wed, fri]      # weekly
  monthly_days: [1, last]        # monthly
cron_expression: null            # cron mode, e.g. '0 9 * * 1-5'
timezone: Asia/Tokyo
```

```yaml
# Plugin event (e.g., GitHub, Slack)
type: trigger-plugin
plugin_id: langgenius/github_trigger
provider_id: langgenius/github_trigger/github
event_name: issues
subscription_id: ''              # Bound after import by the user
plugin_unique_identifier: ''     # Fill only if known
event_parameters: {}
```

### custom-note (Sticky Note, UI only)
`web/app/components/workflow/note-node`. Documentation only; not executed and not connected by edges. Useful for recording skill steps that could not be converted.
```yaml
- data:
    author: ''
    desc: ''
    showAuthor: false
    text: '{"root":{"children":[{"children":[{"detail":0,"format":0,"mode":"normal","style":"","text":"Note text","type":"text","version":1}],"direction":"ltr","format":"","indent":0,"type":"paragraph","version":1}],"direction":"ltr","format":"","indent":0,"type":"root","version":1}}'
    theme: yellow           # blue | cyan | green | yellow | pink | violet
    title: ''
    type: ''
  height: 120
  id: 'note_id'
  position: { x: 0, y: 0 }
  positionAbsolute: { x: 0, y: 0 }
  type: custom-note
  width: 240
```

`text` is a Lexical editor state serialized as a JSON string; keep the structure above and replace only `"Note text"`.

---

## Complete Node Type List

| type | Defined in | Purpose | Generate? |
|------|-----------|---------|-----------|
| `start` | graphon | Input | Yes |
| `end` | graphon | Output (workflow mode) | Yes |
| `answer` | graphon | Output (chat mode) | Yes |
| `llm` | graphon | AI generation / judgment | Yes |
| `tool` | graphon | Plugin / MCP / workflow tool execution | Yes |
| `code` | graphon | Python/JavaScript data processing | Yes |
| `template-transform` | graphon | Jinja2 text formatting | Yes |
| `if-else` | graphon | Conditional branch (IF / ELIF / ELSE) | Yes |
| `question-classifier` | graphon | LLM-based routing | Yes |
| `parameter-extractor` | graphon | LLM structured extraction | Yes |
| `document-extractor` | graphon | File → text | Yes |
| `list-operator` | graphon | Array filter / sort / slice | Yes |
| `variable-aggregator` | graphon | Merge branch outputs | Yes |
| `assigner` | graphon | Write conversation / loop variables | Yes |
| `iteration` + `iteration-start` | graphon | For-each over a list | Yes |
| `loop` + `loop-start` / `loop-end` | graphon | Repeat until condition | Yes |
| `http-request` | graphon | Direct external API call | Yes |
| `variable-assigner` | graphon | Legacy name of `variable-aggregator` | No |
| `knowledge-retrieval` | Dify | RAG search | Yes, if the user supplies dataset IDs |
| `agent` | Dify | Autonomous tool use via agent strategy | Yes |
| `human-input` | Dify (graphon contract) | Form input / approval pause | Yes |
| `trigger-webhook` / `trigger-schedule` / `trigger-plugin` | Dify | External launch | Yes, workflow mode only, instead of `start` |
| `custom-note` | Dify web UI | Sticky note | Yes (documentation) |
| `agent` v2 (`agent_node_kind: dify_agent`) | Dify | Workspace-bound Dify Agent | No |
| `knowledge-index` / `datasource` | Dify | RAG pipeline (`kind: rag_pipeline`) only | No |

---

## Edge Structure

```yaml
- data:
    isInIteration: false          # true for edges between iteration children
    isInLoop: false               # true for edges between loop children
    sourceType: start
    targetType: llm
  id: source_id-source-target_id-target
  selected: false
  source: source_node_id
  sourceHandle: source            # See handle table below
  target: target_node_id
  targetHandle: target
  type: custom
  zIndex: 0                       # 0 at top level; 1002 inside iteration / loop
```

Edges inside a container also carry `iteration_id: 'parent_id'` or `loop_id: 'parent_id'` in `data`.

### sourceHandle by node type

| Source node | sourceHandle values |
|-------------|--------------------|
| most nodes | `source` |
| `if-else` | each case's `case_id`; `false` for ELSE |
| `question-classifier` | each class `id` |
| `human-input` | each `user_actions[].id`; `__timeout` on timeout |
| any node with `error_strategy: fail-branch` | `source` (success) and `fail-branch` |

---

## Skill → Dify Node Mapping Table

| Pattern in Skill | Dify type | Notes |
|-----------------|-----------|-------|
| Claude decides / generates / interprets | `llm` | |
| Claude must output JSON with a fixed shape | `llm` with `structured_output` | Or `parameter-extractor` for field extraction |
| Claude uses tools autonomously in a loop | `agent` | Only when the tool order is not fixed; otherwise chain `tool` nodes |
| Python / JS script execution | `code` | Bash/shell scripts cannot run; rewrite as Python or flag to the user |
| Web search / plugin tool | `tool` | Specified via provider_id |
| MCP server tool call | `tool` with `provider_type: mcp` | Requires the MCP server in the workspace |
| Direct REST API call | `http-request` | URL must appear in the source skill |
| if/else branching on a value | `if-else` | Multiple cases for ELIF |
| "Depending on the type of request..." | `question-classifier` | One class per route |
| Read a PDF / DOCX / uploaded file | `start` (file) → `document-extractor` | |
| Loop over list | `iteration` | List specified via iterator_selector |
| Retry / refine until good enough | `loop` | Break condition + loop_variables |
| Filter / sort / take top N of a list | `list-operator` | |
| Ask the user / wait for approval mid-flow | `human-input` | Actions become branches |
| Search reference docs semantically | `knowledge-retrieval` | Otherwise embed references in the prompt |
| Write to variable / accumulate state | `assigner` | Conversation or loop variables |
| Text formatting from a template | `template-transform` | |
| Merge multiple outputs | `variable-aggregator` | |
| Runs on a schedule / on webhook / on app event | `trigger-*` | Replaces `start` |
| Step that cannot be converted | `custom-note` | Explain what the user must do manually |
| Input | `start` | |
| Final output | `end` (workflow) / `answer` (chat) | |

---

## conversation_variables (Cross-Turn Variables)

advanced-chat only. Used when maintaining state across turns:

```yaml
conversation_variables:
- description: ''
  id: uuid-here
  name: findings
  selector:
  - conversation
  - findings
  value: []
  value_type: array[string]    # string | number | boolean | object | array[string] | array[number] | array[boolean] | array[object]
```

## environment_variables

Use for configuration such as API keys; secret values are never exported, so leave them empty:

```yaml
environment_variables:
- description: 'API key for service X'
  id: uuid-here
  name: API_KEY
  selector:
  - env
  - API_KEY
  value: ''
  value_type: secret           # string | number | secret
```

Reference as `{{#env.API_KEY#}}` or `[env, API_KEY]`.

---

## Variable Reference Syntax

Referencing another node's output in a node's input:

```
{{#node_id.field_name#}}          # Syntax used inside text templates
{{#sys.query#}}                   # System variables: sys.query, sys.files, sys.user_id, sys.conversation_id, ...
{{#env.NAME#}} / {{#conversation.NAME#}}
```

Reference via YAML value_selector:
```yaml
value_selector:
- node_id
- field_name
```

---

## Node Output Fields

The `???` part when a subsequent node references via `value_selector: [node_id, ???]`. Core node outputs match the `NodeRunResult(outputs=...)` in each graphon node implementation.

### Core nodes (graphon)

| Node | Output keys |
|------|-------------|
| `start` | Each `variables[].variable` (e.g. `[start, query]`) |
| `end` | — (terminal) |
| `answer` | `answer`, `files` (rarely referenced) |
| `llm` | `text`, `reasoning_content` (separated mode), `usage`, `finish_reason`, `structured_output` (when enabled), `files` |
| `tool` | `text`, `files`, `json`, plus tool-specific keys |
| `code` | Each key in `outputs` (e.g. `[code_node, result]`) |
| `template-transform` | `output` |
| `if-else` | `result` (bool), `selected_case_id`; routing is via sourceHandle |
| `question-classifier` | `class_name`, `class_label`, `class_id`, `usage` |
| `parameter-extractor` | Each `parameters[].name`, plus `__is_success`, `__reason`, `__usage` |
| `document-extractor` | `text` (string for one file, array[string] for a file list) |
| `list-operator` | `result`, `first_record`, `last_record` |
| `variable-aggregator` | `output`; group mode: `[va_node, group_name, output]` |
| `assigner` | — |
| `iteration` | `output` (array of each round's `output_selector` value). Inside: `[iteration_id, item]`, `[iteration_id, index]` (0-based) |
| `loop` | Each `loop_variables[].label`, plus `loop_round`. Inside: read/write `[loop_id, label]` |
| `http-request` | `status_code`, `body` (empty if files), `headers`, `files` |
| `iteration-start` / `loop-start` / `loop-end` | — |
| any node on its `fail-branch` path | `error_message`, `error_type` |

### Dify-specific nodes

| Node | Output keys |
|------|-------------|
| `knowledge-retrieval` | `result` (array[object]; each element has content, title, metadata) |
| `agent` | `text`, `files`, `json`, `usage` |
| `human-input` | Each `inputs[].output_variable_name`, plus `__action_id`, `__action_value` (action title), `__rendered_content` |
| `trigger-webhook` | Each `name` in `headers` / `params` / `body` |
| `trigger-schedule` | System run metadata (rarely referenced) |
| `trigger-plugin` | Fields of the plugin's event schema |
| `custom-note` | — |

---

## Input Passing Patterns

### Pattern 1: variables + value_selector

Used by `code`, `template-transform`, `end`:
```yaml
variables:
- value_selector:
  - source_node_id
  - field_name
  variable: local_var_name   # Variable name within this node
```

### Pattern 2: Template syntax `{{#node_id.field#}}`

Used in `llm` prompt_template, `answer`, `http-request` url/body/headers, `tool` tool_parameters (`type: mixed`), `human-input` form_content, agent `query`/`instruction`:
```yaml
prompt_template:
- role: user
  text: 'Please process {{#start.query#}}'
```

### Pattern 3: Dedicated selector fields

| Node | Field |
|------|-------|
| `knowledge-retrieval`, `question-classifier` | `query_variable_selector` |
| `parameter-extractor` | `query` |
| `iteration` | `iterator_selector`, `output_selector` |
| `list-operator` | `variable` |
| `document-extractor` | `variable_selector` |
| `variable-aggregator` | `variables` (list of selectors) |
| `assigner` | `items[].variable_selector`, `items[].value` |
| `if-else`, `loop` | `conditions[].variable_selector` |

### Pattern 4: type + value parameters

`tool.tool_parameters`, `agent.agent_parameters`, and `trigger-plugin.event_parameters` specify each parameter via type + value:
```yaml
query:
  type: variable      # selector list
  value: [start, query]
max_iterations:
  type: constant      # literal
  value: 5
prompt:
  type: mixed         # template string
  value: 'Context: {{#kb_node.result#}}'
```
