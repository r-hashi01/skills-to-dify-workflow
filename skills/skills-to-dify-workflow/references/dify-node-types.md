# Dify DSL Reference (YAML Format)

Accurate Dify DSL structures extracted from real sample files (DeepResearch.yml, Text Polishing.yml).
Follow this reference when generating export YAML.

---

## Overall File Structure

```yaml
app:
  description: ''
  icon: 🤖
  icon_background: '#FFEAD5'
  mode: workflow        # workflow | advanced-chat | agent-chat
  name: App Name
  use_icon_as_answer_icon: false
dependencies: []        # Plugins used (Tavily, OpenAI, etc.)
kind: app
version: 0.5.0
workflow:
  conversation_variables: []   # Variables persisted across conversation turns
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
  type: custom
  width: 244
```

Nodes inside an iteration require additional fields:
```yaml
  data:
    isInIteration: true
    iteration_id: 'parent_iteration_node_id'
  parentId: 'parent_iteration_node_id'
  zIndex: 1002
```

---

## Data Fields by Node Type

### start (Entry Point)
```yaml
type: start
variables:
- label: Input Label
  max_length: 48
  options: []
  required: true
  type: paragraph     # text-input | paragraph | number | select
  variable: variable_name
```

### answer (Final Output)
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
memory:                           # Only when using conversation history
  query_prompt_template: '{{#sys.query#}}'
  role_prefix:
    assistant: ''
    user: ''
  window:
    enabled: false
    size: 50
```

**Model name and provider notes**:
- `name` and `provider` depend on the model plugin installed in the user's Dify environment
- Available model names can be found at https://github.com/langgenius/dify-official-plugins under `models/<provider>/models/llm/` YAML filenames
- `completion_params` also vary by provider. For example, `response_format` is `json_object` for OpenAI and `JSON | XML` for Anthropic. Refer to each provider's `models/llm/<model>.yaml` `parameter_rules`
- When assembling YAML, confirm the model with the user and reference the relevant plugin definition for correct parameters

### tool (External Tool)
```yaml
type: tool
provider_id: tavily
provider_name: tavily
provider_type: builtin
tool_label: Tavily Search
tool_name: tavily_search
tool_configurations:
  search_depth: advanced
  max_results: 5
  topic: general
tool_parameters:
  query:
    type: mixed
    value: '{{#node_id.field#}}'
```

### code (Python Code Execution)
```yaml
type: code
code_language: python3
code: |
  def main(input_var: str) -> dict:
      return {"result": input_var}
outputs:
  result:
    children: null
    type: string
  array:
    children: null
    type: array[number]
variables:
- value_selector:
  - start_node_id
  - variable_name
  variable: input_var
```

### if-else (Conditional Branch)
```yaml
type: if-else
cases:
- case_id: 'true'
  conditions:
  - comparison_operator: is          # is | is-not | contains | not-contains | start-with | end-with | empty | not-empty
    id: uuid-here
    value: 'True'
    varType: string
    variable_selector:
    - node_id
    - field_name
  id: 'true'
  logical_operator: and
```

Edge sourceHandle is `'true'` or `'false'`.

### iteration (List Loop Processing)
```yaml
type: iteration
error_handle_mode: terminated    # terminated | continue-on-error | remove-abnormal-output
is_parallel: false
iterator_selector:
- code_node_id
- array_field
output_selector:
- inner_aggregator_node_id
- output
output_type: array[string]
parallel_nums: 10
start_node_id: iteration_idstart  # iteration node's id + "start"
height: 1042
width: 1186
```

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

### assigner (Variable Assignment)
```yaml
type: assigner
version: '2'
items:
- input_type: variable
  operation: over-write     # over-write | append | clear
  value:
  - source_node_id
  - field_name
  variable_selector:
  - conversation            # or other scope
  - variable_name
  write_mode: over-write
```

### template-transform (Text Template)
```yaml
type: template-transform
template: '{{ var1 }}/{{ var2 }} processing iteration'
variables:
- value_selector:
  - node_id
  - field
  variable: var1
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
```

### end (Workflow Termination)
`workflow` mode only. Defines output variables and returns the workflow's final result (`advanced-chat` mode uses `answer` instead).
```yaml
type: end
outputs:
- value_selector:
  - node_id
  - field
  variable: output_text
```

### http-request (External API Call)
```yaml
type: http-request
method: post       # get | post | put | patch | delete | head | options
url: 'https://api.example.com/data'
headers: 'Content-Type: application/json'
params: ''
body:
  type: json       # none | form-data | x-www-form-urlencoded | raw-text | json | binary
  data: '{"key":"{{#node_id.value#}}"}'
authorization:
  type: no-auth    # no-auth | api-key
  config: null
timeout:
  connect: 10
  read: 60
  write: 20
ssl_verify: true
```

### knowledge-retrieval (Knowledge Base Search)
RAG. Searches and retrieves documents relevant to a query from a knowledge base.
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
  score_threshold: 0.5
  reranking_enable: false
metadata_filtering_mode: disabled  # disabled | automatic | manual
```

### question-classifier (Question Classification)
Uses an LLM to classify user questions into categories, branching to subsequent nodes per category. Edge sourceHandle is the class_id.
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
- id: class-uuid-1
  name: 'Technical question'
- id: class-uuid-2
  name: 'General question'
instruction: ''
```

### parameter-extractor (Parameter Extraction)
Uses an LLM to extract structured parameters from text.
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
- name: city
  type: string     # string | number | boolean | array[string] | array[number] | array[object]
  description: 'City name to extract'
  required: true
reasoning_mode: function_call   # function_call | prompt
instruction: ''
```

### document-extractor (File Text Extraction)
Extracts text content from file variables such as PDFs and Word documents.
```yaml
type: document-extractor
variable_selector:
- start
- file
```

### list-operator (List Operations)
Performs filtering, sorting, top-N retrieval, and index extraction on lists.
```yaml
type: list-operator
variable:
- node_id
- list_output
filter_by:
  enabled: true
  conditions:
  - key: name
    comparison_operator: contains
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
  serial: '1'
```

### loop (Conditional Loop)
Repeats internal nodes until a condition is met or the maximum count is reached (equivalent to a while loop). Contains `loop-start` and `loop-end` as internal sub-nodes.
```yaml
type: loop
start_node_id: 'loop_idstart'
loop_count: 10
logical_operator: and
break_conditions:
- id: cond-uuid
  variable_selector:
  - node_id
  - counter
  comparison_operator: "≥"
  value: '5'
  varType: number
loop_variables:
- id: var-uuid
  label: counter
  var_type: number
  value_type: constant
  value: 0
```

### agent (Agent)
Autonomously invokes tools based on an agent strategy defined by a plugin.
```yaml
type: agent
agent_strategy_provider_name: langgenius/agent
agent_strategy_name: function_calling
agent_strategy_label: Function Calling
agent_parameters:
  query:
    type: variable
    value:
    - start
    - query
  tools:
    type: mixed
    value: []
memory:
  role_prefix:
    user: ''
    assistant: ''
  window:
    enabled: false
    size: 50
```

### human-input (Awaiting Human Input)
Waits for form input or action button selection from a human during workflow execution.
```yaml
type: human-input
delivery_methods:
- type: webapp
  enabled: true
  id: uuid
form_content: 'Please enter the following information'
inputs:
- type: text-input     # text-input | paragraph | number | single-file
  output_variable_name: user_response
  default: null
user_actions:
- id: approve
  title: 'Approve'
  button_style: primary   # primary | default
- id: reject
  title: 'Reject'
  button_style: default
timeout: 36
timeout_unit: hour    # hour | day
```

### trigger-webhook / trigger-schedule / trigger-plugin (External Triggers)
Special start nodes that define workflow launch triggers instead of `start`.
```yaml
# Webhook
type: trigger-webhook
method: POST
content_type: application/json

# Scheduled execution
type: trigger-schedule
mode: visual    # visual | cron
frequency: daily   # hourly | daily | weekly | monthly
timezone: Asia/Tokyo

# Plugin event (e.g., Slack)
type: trigger-plugin
plugin_id: langgenius/slack
event_name: message_received
```

---

## Complete Node Type List

| type | Purpose | Corresponding Skill Pattern |
|------|---------|---------------------------|
| `start` | Input | Initial user input |
| `end` | Output (workflow mode) | Final deliverable output |
| `answer` | Output (chat mode) | Final deliverable output / streaming response |
| `llm` | AI | Claude decides, generates, or interprets |
| `tool` | Tool | Plugin tool execution (search, API, etc.) |
| `http-request` | External | Direct external API call |
| `code` | Transform | Python/JS code execution, data processing |
| `if-else` | Branch | if/else conditional branching |
| `question-classifier` | AI Branch | Routing by question content |
| `iteration` | Loop | Process each list element sequentially |
| `iteration-start` | Internal | Iteration internal start (auto-generated) |
| `loop` | Loop | Repeat until condition is met (while-loop equivalent) |
| `loop-start` / `loop-end` | Internal | Loop internal nodes (auto-generated) |
| `knowledge-retrieval` | Search | RAG search from knowledge base |
| `knowledge-index` | RAG | Knowledge base indexing |
| `parameter-extractor` | AI Extract | Extract structured parameters via LLM |
| `document-extractor` | Transform | Extract text from PDF/Word |
| `list-operator` | Operation | List filter, sort, slice |
| `template-transform` | Transform | String generation via Jinja2 template |
| `variable-aggregator` | Variable | Merge outputs from multiple paths |
| `assigner` | Variable | Write values to conversation variables |
| `agent` | AI | Autonomously execute tools via agent strategy |
| `human-input` | Human | Form input / approval wait |
| `trigger-webhook` | Trigger | Launch workflow via webhook |
| `trigger-schedule` | Trigger | Launch workflow on schedule |
| `trigger-plugin` | Trigger | Launch workflow via plugin event |
| `datasource` | RAG | External data source retrieval (RAG pipeline) |
| `custom-note` | UI | Memo node (no effect on flow) |

---

## Edge Structure

```yaml
- data:
    isInIteration: false          # false if outside iteration
    sourceType: start
    targetType: llm
  id: source_id-source-target_id-target
  selected: false
  source: source_node_id
  sourceHandle: source            # Usually "source"; for if-else: "true" or "false"
  target: target_node_id
  targetHandle: target
  type: custom
  zIndex: 0                       # Usually 0; 1002 inside iteration
```

Edges inside iteration:
```yaml
  data:
    isInIteration: true
    iteration_id: 'parent_iteration_node_id'
    sourceType: llm
    targetType: tool
  zIndex: 1002
```

---

## Skill → Dify Node Mapping Table

| Pattern in Skill | Dify type | Notes |
|-----------------|-----------|-------|
| Claude decides/generates | `llm` | |
| Python/bash script execution | `code` | |
| External API / web search | `tool` | Specified via provider_id |
| if/else branching | `if-else` | Edge sourceHandle is "true"/"false" |
| Loop over list | `iteration` | List specified via iterator_selector |
| Write to variable | `assigner` | Used for read/write to conversation variables |
| Text formatting | `template-transform` | |
| Merge multiple outputs | `variable-aggregator` | |
| Input | `start` | |
| Final output | `answer` | |

---

## conversation_variables (Cross-Turn Variables)

Used when maintaining state across turns, such as accumulating LLM outputs during loop processing:

```yaml
conversation_variables:
- description: ''
  id: uuid-here
  name: findings
  selector:
  - conversation
  - findings
  value: []
  value_type: array[string]    # string | number | array[string] | object
```

---

## Variable Reference Syntax

Referencing another node's output in a node's input:

```
{{#node_id.field_name#}}          # Syntax used inside text templates
```

Reference via YAML value_selector:
```yaml
value_selector:
- node_id
- field_name
```

---

## Node Output Fields

The `???` part when a subsequent node references via `value_selector: [node_id, ???]`.
Verified from GitHub source code (`api/dify_graph/nodes/`) `NodeRunResult(outputs=...)`.

### start
```
Variables defined in the variables field become output keys directly
Example: variable: "query" → value_selector: [start, query]
```

### end / answer
end is an output-only node and is not a reference target for subsequent nodes.
answer node outputs are `answer` and `files`, but they are rarely referenced by subsequent nodes.

### llm
```
text              # Generated text (main output)
reasoning_content # Reasoning content (thinking models only)
usage             # Token usage
finish_reason     # Finish reason
structured_output # Structured output (only when structured output is enabled)
files             # Generated files (only when file output is enabled)
```

### tool (Plugin Tool)
```
text              # Text output (main output)
files             # File output
json              # JSON output
# Tool-specific variables may also be added
```

### code
```
Keys defined in the outputs field become output keys directly
Example: outputs: { result: {type: string} } → value_selector: [code_node, result]
```

### knowledge-retrieval
```
result            # Search results (ArrayObject type. Each element contains document chunk info)
```

### http-request
```
status_code       # HTTP status code (integer)
body              # Response body (text; empty string if files exist)
headers           # Response headers
files             # Downloaded files (for binary responses)
```

### parameter-extractor
```
# Defined parameter names become output keys directly
# Example: parameters: [{name: city}] → value_selector: [pe_node, city]
__is_success      # 1 if extraction succeeded, 0 if failed
__reason          # Failure reason (only on failure)
__usage           # Token usage
```

### document-extractor
```
text              # Extracted text
                  # Single file: string type
                  # Multiple files: ArrayString type (array of strings)
```

### list-operator
```
result            # The entire list after operations
first_record      # First element of the list (for extracting a single item)
last_record       # Last element of the list
```

### template-transform
```
output            # String result of rendering the template
```

### variable-aggregator
Normal mode:
```
output            # Aggregated variable
```
Group mode (when using groups for output_type):
```
{group_name}.output  # Nested by group name
# Reference: value_selector: [va_node, group_name, output]
```

### if-else
Has no output fields. Edge sourceHandle is `'true'` or `'false'`.

### question-classifier
```
class_name        # Name of the classified class
class_id          # ID of the classified class
usage             # Token usage
```
Edge sourceHandle is the `class_id` (the id defined in the classes field).

### iteration (List Loop Processing)
Output referenced from outside:
```
output            # Array collecting each iteration's output_selector results
```
Special variables accessible from nodes inside the iteration (use the iteration's own id as the node_id part of value_selector):
```
item              # Current list element being processed
index             # Current index (0-based)
```

### loop (Conditional Loop)
```
# Each variable's label name defined in loop_variables becomes an output key
# Example: loop_variables: [{label: counter}] → value_selector: [loop_node, counter]
loop_round        # How many times the loop executed (value at termination)
```

### agent
```
text              # Agent's final text output
files             # File output
json              # JSON output
usage             # Token usage
# Tool-defined variables may also be added
```

### human-input
```
# output_variable_name defined in inputs becomes an output key directly
# Example: inputs: [{output_variable_name: user_response}] → value_selector: [hi_node, user_response]
__action_id           # ID of the action the user selected
__rendered_content    # Rendered form content
```
Edge sourceHandle:
- When user selects an action: the action `id` defined in `user_actions`
- On timeout: `__timeout`

### assigner
Has no output fields (only writes to conversation variables).

### loop-start / loop-end / iteration-start
Internal sub-nodes; not referenced by subsequent nodes.

---

## Input Passing Patterns

### Pattern 1: variables + value_selector (Reference variables via YAML fields)

Used by many nodes including `code`, `template-transform`, `variable-aggregator`, `assigner`:
```yaml
variables:
- value_selector:
  - source_node_id
  - field_name
  variable: local_var_name   # Variable name within this node
```

### Pattern 2: Template syntax `{{#node_id.field#}}`

Used in `llm` prompt_template, `answer` answer field, `http-request` url/body/headers, `tool` tool_parameters, etc.:
```yaml
# llm prompt_template example
prompt_template:
- role: user
  text: 'Please process {{#start.query#}}'

# http-request body example
body:
  type: json
  data: '{"input": "{{#llm_node.text#}}"}'

# tool tool_parameters example
tool_parameters:
  query:
    type: mixed
    value: '{{#start.query#}}'
```

### Pattern 3: query_variable_selector (Query-specific reference)

`knowledge-retrieval` and `question-classifier` use a dedicated field for queries:
```yaml
query_variable_selector:
- start           # Node ID
- query           # Field name
```

### Pattern 4: iterator_selector (Iteration list specification)

The `iteration` node uses a dedicated field to specify the loop target list:
```yaml
iterator_selector:
- code_node_id
- array_field
```

### Pattern 5: variable (list-operator input)

`list-operator` uses a dedicated field to specify the input list:
```yaml
variable:
- node_id
- list_output
```

### Pattern 6: variable_selector (document-extractor input)

`document-extractor` uses a dedicated field to specify file variables:
```yaml
variable_selector:
- start
- file
```

### Pattern 7: agent_parameters (Agent input)

The `agent` node specifies each parameter via type + value:
```yaml
agent_parameters:
  query:
    type: variable
    value:
    - start
    - query
  # Constant value
  max_iterations:
    type: constant
    value: 5
  # Template
  prompt:
    type: mixed
    value: 'Context: {{#kb_node.result#}}'
```
