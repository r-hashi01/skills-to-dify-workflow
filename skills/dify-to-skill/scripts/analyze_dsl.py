# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Summarize a Dify DSL YAML for conversion into a Claude Code skill.

Usage:
  uv run analyze_dsl.py <app.yml>                     Overview: steps in execution order, branches,
                                                      variable sources, portability, security findings
  uv run analyze_dsl.py <app.yml> --node <id>         Full data of one node (prompts, code, templates)
  uv run analyze_dsl.py <app.yml> --extract-code DIR  Write each code node to DIR as a runnable script
  uv run analyze_dsl.py <app.yml> --graph-json        Nodes and edges as JSON (input of explain-dify-dsl's renderer)
  uv run analyze_dsl.py <app.yml> --content           Every prompt / code / template in execution order, with
                                                      {{#node.field#}} rewritten as ⟨Node title › field⟩

The YAML is only parsed (yaml.safe_load). Nothing in it is executed or fetched.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

CURRENT_DSL_VERSION = "0.7.0"
REF_RE = re.compile(r"\{\{#([^#}]+)#\}\}")
URL_RE = re.compile(r"https?://[^\s'\"<>{}`)]+")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SPECIAL_SCOPES = {"sys", "env", "conversation"}

# How each node type carries over into a skill (see references/node-to-skill-mapping.md)
PORTABILITY = {
    "start": "native", "end": "native", "answer": "native", "llm": "native",
    "if-else": "native", "question-classifier": "native", "iteration": "native",
    "loop": "native", "template-transform": "native", "variable-aggregator": "native",
    "assigner": "native", "list-operator": "native", "parameter-extractor": "native",
    "document-extractor": "native", "human-input": "native", "agent": "native",
    "code": "script", "http-request": "script",
    "tool": "manual", "knowledge-retrieval": "manual", "trigger-schedule": "manual",
    "trigger-webhook": "unsupported", "trigger-plugin": "unsupported",
    "datasource": "unsupported", "knowledge-index": "unsupported",
}
INTERNAL_TYPES = {"iteration-start", "loop-start", ""}

RISKY_CODE = [
    (r"\b(os\.system|subprocess|pty\.spawn|os\.exec\w*|os\.popen)\b", "runs shell commands"),
    (r"\b(eval|exec|compile|__import__)\s*\(", "dynamic code execution"),
    (r"\b(socket|requests|urllib|httpx|http\.client|aiohttp|fetch|XMLHttpRequest)\b", "network access"),
    (r"\bopen\s*\(|\bshutil\b|\bos\.(remove|unlink|rmdir|makedirs|chmod)\b|\bfs\.", "file system access"),
    (r"\b(base64|marshal|pickle|codecs\.decode)\b", "encoded or serialized payloads"),
    (r"\bos\.environ\b|\bprocess\.env\b", "reads environment variables"),
]
INJECTION_HINTS = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous)"
    r"|you are now|reveal (the |your )?(system prompt|instructions)|exfiltrat|do not tell the user",
    re.IGNORECASE,
)
PY_STDLIB = set(getattr(sys, "stdlib_module_names", ()))


def walk_strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


def walk_selectors(obj):
    """Yield variable selectors ([node_id, field, ...]) found in structured fields."""
    def is_selector(v):
        return isinstance(v, list) and len(v) >= 2 and all(isinstance(x, str) for x in v)

    if isinstance(obj, dict):
        # value is a selector when the item says so (assigner, tool/agent params, loop variables)
        value_is_variable = "variable" in (obj.get("input_type"), obj.get("type"), obj.get("value_type"))
        for k, v in obj.items():
            if (k.endswith("selector") or (k == "value" and value_is_variable)) and is_selector(v):
                yield v
            else:
                yield from walk_selectors(v)
    elif isinstance(obj, list):
        if obj and all(is_selector(x) for x in obj):
            yield from obj  # variable-aggregator style: list of selectors
        else:
            for v in obj:
                yield from walk_selectors(v)


class Dsl:
    def __init__(self, data):
        self.data = data
        self.app = data.get("app", {})
        wf = data.get("workflow") or {}
        graph = wf.get("graph") or {}
        self.workflow = wf
        self.nodes = {n["id"]: n for n in graph.get("nodes", []) if n.get("type") != "custom-note"}
        self.notes = [n for n in graph.get("nodes", []) if n.get("type") == "custom-note"]
        self.edges = graph.get("edges", [])
        self.out = defaultdict(list)
        self.indeg = defaultdict(int)
        for e in self.edges:
            if e.get("source") in self.nodes and e.get("target") in self.nodes:
                self.out[e["source"]].append(e)
                self.indeg[e["target"]] += 1
        self.children = defaultdict(list)
        for nid, n in self.nodes.items():
            if n.get("parentId"):
                self.children[n["parentId"]].append(nid)

    def dtype(self, nid):
        return (self.nodes[nid].get("data") or {}).get("type", "")

    def title(self, nid):
        if nid in SPECIAL_SCOPES:
            return nid
        n = self.nodes.get(nid)
        return (n.get("data") or {}).get("title") or nid if n else f"<missing {nid}>"

    def order(self, ids):
        """Topological order over the given node ids, ties broken by canvas position."""
        ids = [i for i in ids if self.dtype(i) not in INTERNAL_TYPES]
        idset = set(ids)
        indeg = {i: sum(1 for e in self.edges if e.get("target") == i and e.get("source") in idset) for i in ids}
        pos = {i: ((self.nodes[i].get("position") or {}).get("x", 0), (self.nodes[i].get("position") or {}).get("y", 0))
               for i in ids}
        ready = sorted((i for i in ids if indeg[i] == 0), key=lambda i: pos[i])
        result = []
        while ready:
            cur = ready.pop(0)
            result.append(cur)
            for e in self.out[cur]:
                t = e["target"]
                if t in indeg:
                    indeg[t] -= 1
                    if indeg[t] == 0:
                        ready.append(t)
                        ready.sort(key=lambda i: pos[i])
        result += [i for i in ids if i not in result]  # cycles: append the rest
        return result

    def ref_label(self, selector):
        head = selector[0]
        field = ".".join(selector[1:])
        if head in SPECIAL_SCOPES:
            return f"{head}.{field}"
        return f"[{self.title(head)}].{field}"

    def inputs_of(self, nid):
        data = dict(self.nodes[nid].get("data") or {})
        if not (data.get("vision") or {}).get("enabled"):
            data.pop("vision", None)  # disabled vision still carries a default [sys, files] selector
        refs = []
        for _, s in walk_strings(data):
            refs += [r.split(".") for r in REF_RE.findall(s)]
        refs += list(walk_selectors(data))
        seen, labels = set(), []
        for r in refs:
            if not r or r[0] == nid or r[0] == "$output" or r == ["context"]:
                continue
            key = tuple(r)
            if key not in seen:
                seen.add(key)
                labels.append(self.ref_label(r))
        return labels

    def cond_text(self, c):
        sel = c.get("variable_selector") or []
        lhs = self.ref_label(sel) if sel else "?"
        val = c.get("value")
        if isinstance(val, list) and len(val) >= 2 and val[0] in self.nodes:
            val = self.ref_label(val)
        return f"{lhs} {c.get('comparison_operator')} {val!r}" if val not in (None, "") else \
            f"{lhs} {c.get('comparison_operator')}"

    def branch_label(self, nid, handle):
        data = self.nodes[nid].get("data") or {}
        t = data.get("type")
        if handle == "fail-branch":
            return "on error"
        if t == "if-else":
            if handle == "false":
                return "ELSE"
            for case in data.get("cases") or []:
                if case.get("case_id") == handle:
                    joiner = f" {case.get('logical_operator', 'and').upper()} "
                    return "IF " + joiner.join(self.cond_text(c) for c in case.get("conditions") or [])
        if t == "question-classifier":
            for cls in data.get("classes") or []:
                if cls.get("id") == handle:
                    return f"class: {cls.get('label') or cls.get('name')}"
        if t == "human-input":
            if handle == "__timeout":
                return "on timeout"
            for a in data.get("user_actions") or []:
                if a.get("id") == handle:
                    return f"action: {a.get('title')}"
        return None if handle in (None, "source") else handle


def summarize_node(dsl, nid):
    data = dsl.nodes[nid].get("data") or {}
    t = data.get("type")
    lines = []
    if t == "start":
        for v in data.get("variables") or []:
            opt = f" options={v.get('options')}" if v.get("options") else ""
            lines.append(f"input `{v.get('variable')}` ({v.get('type')}{', required' if v.get('required') else ''})"
                         f" — {v.get('label')}{opt}")
    elif t == "llm":
        model = data.get("model") or {}
        lines.append(f"model: {model.get('provider')} / {model.get('name')}")
        pt = data.get("prompt_template")
        msgs = pt if isinstance(pt, list) else [pt or {}]
        for m in msgs:
            text = m.get("text") or m.get("jinja2_text") or ""
            lines.append(f"{m.get('role', 'prompt')} prompt: {len(text)} chars")
        if (data.get("context") or {}).get("enabled"):
            lines.append(f"context from: {dsl.ref_label(data['context'].get('variable_selector') or ['?'])}")
        if data.get("structured_output_enabled") and data.get("structured_output"):
            props = ((data["structured_output"].get("schema") or {}).get("properties") or {}).keys()
            lines.append(f"structured output fields: {', '.join(props)}")
        if data.get("memory"):
            lines.append("uses conversation memory")
    elif t == "code":
        lines.append(f"language: {data.get('code_language')}; "
                     f"inputs: {', '.join(v.get('variable', '?') for v in data.get('variables') or [])}; "
                     f"outputs: {', '.join((data.get('outputs') or {}).keys())}")
        mods = sorted(set(re.findall(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", data.get("code") or "", re.M)))
        third = [m for m in mods if PY_STDLIB and m not in PY_STDLIB]
        if mods:
            lines.append(f"imports: {', '.join(mods)}" + (f" (non-stdlib: {', '.join(third)})" if third else ""))
    elif t == "http-request":
        auth = (data.get("authorization") or {}).get("type")
        lines.append(f"{str(data.get('method', '')).upper()} {data.get('url')} (auth: {auth}, "
                     f"body: {(data.get('body') or {}).get('type')})")
    elif t == "tool":
        lines.append(f"provider: {data.get('provider_id')} ({data.get('provider_type')}); "
                     f"tool: {data.get('tool_name')} — {data.get('tool_label')}")
    elif t == "knowledge-retrieval":
        lines.append(f"datasets: {len(data.get('dataset_ids') or [])} (IDs are workspace-specific)")
    elif t == "template-transform":
        lines.append(f"jinja2 template: {len(data.get('template') or '')} chars")
    elif t == "question-classifier":
        for cls in data.get("classes") or []:
            lines.append(f"class `{cls.get('id')}`: {cls.get('name')}")
    elif t == "parameter-extractor":
        for p in data.get("parameters") or []:
            lines.append(f"param `{p.get('name')}` ({p.get('type')}): {p.get('description')}")
    elif t == "iteration":
        lines.append(f"for each item of {dsl.ref_label(data.get('iterator_selector') or ['?'])}; "
                     f"collects {dsl.ref_label(data.get('output_selector') or ['?'])}"
                     f"{' (parallel)' if data.get('is_parallel') else ''}")
    elif t == "loop":
        conds = f" {data.get('logical_operator', 'and').upper()} ".join(
            dsl.cond_text(c) for c in data.get("break_conditions") or [])
        lines.append(f"repeat up to {data.get('loop_count')} times until: {conds or '(no condition)'}")
        for v in data.get("loop_variables") or []:
            lines.append(f"loop variable `{v.get('label')}` ({v.get('var_type')}) = {v.get('value')!r}")
    elif t == "human-input":
        lines.append(f"form fields: {', '.join(i.get('output_variable_name', '?') for i in data.get('inputs') or [])}; "
                     f"actions: {', '.join(a.get('title', '?') for a in data.get('user_actions') or [])}")
    elif t in ("end",):
        for o in data.get("outputs") or []:
            lines.append(f"output `{o.get('variable')}` = {dsl.ref_label(o.get('value_selector') or ['?'])}")
    elif t == "answer":
        lines.append(f"answer template: {(data.get('answer') or '')[:120]!r}")
    elif t and t.startswith("trigger-"):
        lines.append(json.dumps({k: data.get(k) for k in ("mode", "frequency", "cron_expression", "timezone",
                                                          "method", "plugin_id", "event_name") if data.get(k)}))
    return lines


def render_steps(dsl, ids, depth, counter, out):
    pad = "  " * depth
    for nid in dsl.order(ids):
        data = dsl.nodes[nid].get("data") or {}
        t = data.get("type")
        counter[0] += 1
        port = PORTABILITY.get(t, "unknown")
        out.append(f"{pad}{counter[0]}. **{dsl.title(nid)}** — `{t}` [{port}] (id: `{nid}`)")
        for line in summarize_node(dsl, nid):
            out.append(f"{pad}   - {line}")
        ins = dsl.inputs_of(nid) if t != "end" else []  # end already lists its sources
        if ins:
            out.append(f"{pad}   - reads: {', '.join(ins)}")
        if data.get("error_strategy"):
            out.append(f"{pad}   - error strategy: {data['error_strategy']}")
        if dsl.children.get(nid):
            out.append(f"{pad}   - body:")
            render_steps(dsl, dsl.children[nid], depth + 2, counter, out)
        for e in dsl.out[nid]:
            label = dsl.branch_label(nid, e.get("sourceHandle"))
            nxt = dsl.title(e["target"])
            out.append(f"{pad}   - → {nxt}" + (f"  ⟵ {label}" if label else ""))


def security_findings(dsl):
    findings = []
    for nid, n in dsl.nodes.items():
        data = n.get("data") or {}
        t = data.get("type")
        if t == "code":
            for i, line in enumerate((data.get("code") or "").splitlines(), 1):
                for pat, why in RISKY_CODE:
                    if re.search(pat, line):
                        findings.append(f"code `{dsl.title(nid)}` line {i}: {why} — `{line.strip()[:100]}`")
        for path, s in walk_strings(data):
            for email in EMAIL_RE.findall(s):
                if "@example." not in email.lower():  # placeholder domains (example.com, example.corp, ...)
                    findings.append(f"hardcoded email address in `{dsl.title(nid)}` ({path}): `{email}`")
            if INJECTION_HINTS.search(s):
                findings.append(f"possible prompt injection in `{dsl.title(nid)}` ({path}): "
                                f"`{INJECTION_HINTS.search(s).group(0)}`")
    return findings


def all_urls(dsl):
    urls = defaultdict(set)
    for nid, n in dsl.nodes.items():
        for path, s in walk_strings(n.get("data") or {}):
            if "icon" in path.rsplit(".", 1)[-1]:  # Dify UI asset URLs, not called by the workflow
                continue
            for u in URL_RE.findall(s):
                urls[u.rstrip(".,;")].add(dsl.title(nid))
    return urls


def overview(dsl, path):
    app, wf = dsl.app, dsl.workflow
    out = [f"# {app.get('name')}", "",
           f"- file: {path}",
           f"- mode: {app.get('mode')}  |  DSL version: {dsl.data.get('version')}"
           + (f"  (expected {CURRENT_DSL_VERSION}; schemas may differ)" if str(dsl.data.get('version')) != CURRENT_DSL_VERSION else ""),
           f"- description: {app.get('description') or '(none)'}",
           f"- nodes: {len(dsl.nodes)} (+{len(dsl.notes)} notes)"]
    if app.get("mode") not in ("workflow", "advanced-chat"):
        out.append(f"- WARNING: mode `{app.get('mode')}` has no workflow graph to convert")
    env = wf.get("environment_variables") or []
    if env:
        out += ["", "## Environment variables"]
        for e in env:
            kind = "secret (value not exported)" if e.get("value_type") == "secret" else f"value: {e.get('value')!r}"
            out.append(f"- `{e.get('name')}` ({e.get('value_type')}) — {kind}")
    conv = wf.get("conversation_variables") or []
    if conv:
        out += ["", "## Conversation variables"]
        out += [f"- `{c.get('name')}` ({c.get('value_type')}) — {c.get('description') or ''}" for c in conv]
    deps = dsl.data.get("dependencies") or []
    if deps:
        out += ["", "## Plugin dependencies"]
        for d in deps:
            v = d.get("value") or {}
            ident = v.get("marketplace_plugin_unique_identifier") or v.get("plugin_unique_identifier") or v.get("repo")
            out.append(f"- {str(ident).split('@')[0]}")
    out += ["", "## Steps (execution order)", "",
            "Portability: native = Claude does it directly; script = becomes a script / shell command;",
            "manual = needs a Claude Code equivalent chosen with the user; unsupported = cannot run in a skill.", ""]
    top = [i for i in dsl.nodes if not dsl.nodes[i].get("parentId")]
    render_steps(dsl, top, 0, [0], out)
    if dsl.notes:
        out += ["", "## Notes on canvas"]
        for n in dsl.notes:
            text = (n.get("data") or {}).get("text") or ""
            plain = " ".join(re.findall(r'"text":"((?:[^"\\]|\\.)*)"', text)) or text
            out.append(f"- {plain[:300]}")
    out += ["", "## Security review input", ""]
    urls = all_urls(dsl)
    out.append("External URLs:" if urls else "External URLs: none")
    out += [f"- {u} (in: {', '.join(sorted(where))})" for u, where in sorted(urls.items())]
    findings = security_findings(dsl)
    out.append("")
    out.append("Flagged patterns:" if findings else "Flagged patterns: none (still review code and prompts yourself)")
    out += [f"- {f}" for f in findings]
    return "\n".join(out)


def node_detail(dsl, nid):
    if nid not in dsl.nodes:
        sys.exit(f"node not found: {nid}")
    data = dict(dsl.nodes[nid].get("data") or {})
    for k in ("selected", "desc") if not data.get("desc") else ("selected",):
        data.pop(k, None)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


DISPLAY_CATEGORY = {
    "start": "start", "trigger-webhook": "start", "trigger-schedule": "start", "trigger-plugin": "start",
    "end": "end", "answer": "end",
    "llm": "llm", "agent": "llm", "parameter-extractor": "llm",
    "tool": "tool", "code": "tool", "http-request": "tool", "knowledge-retrieval": "tool",
    "document-extractor": "tool",
    "if-else": "condition", "question-classifier": "condition",
    "iteration": "loop", "loop": "loop",
    "template-transform": "template", "variable-aggregator": "template", "assigner": "template",
    "list-operator": "template", "loop-end": "template",
    "human-input": "human",
}


def humanize_refs(dsl, text):
    """Rewrite {{#node.field#}} references as ⟨Node title › field⟩ so prompts read on their own."""
    def repl(m):
        parts = m.group(1).split(".")
        if parts == ["context"]:
            return "⟨context: knowledge retrieval result⟩"
        if parts[0] == "$output":
            return f"⟨form field: {'.'.join(parts[1:])}⟩"
        head = parts[0] if parts[0] in SPECIAL_SCOPES else dsl.title(parts[0])
        return f"⟨{head} › {'.'.join(parts[1:])}⟩"
    return REF_RE.sub(repl, text or "")


def sel(selector):
    """A selector as Dify template syntax, so renderers can treat every reference the same way."""
    return "{{#" + ".".join(selector) + "#}}" if selector else ""


def node_fields(dsl, nid):
    """Rows for a node reference page: (section, name, value). Values keep {{#node.field#}} references."""
    data = dsl.nodes[nid].get("data") or {}
    t = data.get("type")
    rows = []

    def row(section, name, value):
        if value is None or value == "" or value == [] or value == {}:
            return
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        rows.append({"section": section, "name": str(name), "value": value})

    def tool_value(v):
        if isinstance(v, dict) and "value" in v:
            val = v.get("value")
            if v.get("type") == "variable" and isinstance(val, list):
                return sel(val)
            return val
        return v

    model = data.get("model") or {}
    if model:
        row("settings", "model", f"{model.get('provider')} / {model.get('name')}")
        for k, v in (model.get("completion_params") or {}).items():
            row("settings", k, v)
    if t == "start":
        for v in data.get("variables") or []:
            row("inputs", v.get("variable"), f"{v.get('label')} ({v.get('type')}"
                f"{', required' if v.get('required') else ', optional'})"
                + (f" options: {', '.join(v.get('options'))}" if v.get("options") else ""))
    elif t == "llm":
        ctx = data.get("context") or {}
        if ctx.get("enabled"):
            row("inputs", "context", sel(ctx.get("variable_selector") or []))
        if data.get("memory"):
            row("settings", "conversation memory", "on")
        if (data.get("vision") or {}).get("enabled"):
            row("inputs", "vision files", sel((data["vision"].get("configs") or {}).get("variable_selector") or []))
        if data.get("structured_output_enabled"):
            row("settings", "structured output", "on")
    elif t == "tool":
        row("settings", "tool", f"{data.get('provider_id')} › {data.get('tool_name')} ({data.get('provider_type')})")
        for k, v in (data.get("tool_parameters") or {}).items():
            row("inputs", k, tool_value(v))
        for k, v in (data.get("tool_configurations") or {}).items():
            row("settings", k, tool_value(v))
    elif t == "http-request":
        row("settings", "request", f"{str(data.get('method', '')).upper()} {data.get('url')}")
        row("settings", "authorization", (data.get("authorization") or {}).get("type"))
        for line in (data.get("headers") or "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                row("inputs", f"header {k.strip()}", v.strip())
        for line in (data.get("params") or "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                row("inputs", f"query {k.strip()}", v.strip())
        body = data.get("body") or {}
        items = body.get("data")
        if isinstance(items, str):
            row("inputs", f"body ({body.get('type')})", items)
        else:
            for it in items or []:
                if isinstance(it, dict):
                    val = sel(it.get("file")) if it.get("type") == "file" else it.get("value")
                    row("inputs", f"body ({body.get('type')})" + (f" {it.get('key')}" if it.get("key") else ""), val)
    elif t in ("code", "template-transform"):
        for v in data.get("variables") or []:
            row("inputs", v.get("variable"), sel(v.get("value_selector") or []))
        if t == "code":
            row("settings", "language", data.get("code_language"))
    elif t == "knowledge-retrieval":
        row("inputs", "query", sel(data.get("query_variable_selector") or []))
        row("settings", "knowledge bases", f"{len(data.get('dataset_ids') or [])} (IDs are workspace-specific)")
        mrc = data.get("multiple_retrieval_config") or {}
        row("settings", "top_k", mrc.get("top_k"))
        row("settings", "score threshold", mrc.get("score_threshold"))
        rr = mrc.get("reranking_model") or {}
        if mrc.get("reranking_enable") and rr:
            row("settings", "reranker", f"{rr.get('provider')} / {rr.get('model')}")
    elif t in ("question-classifier", "parameter-extractor"):
        row("inputs", "query", sel(data.get("query_variable_selector") or data.get("query") or []))
    elif t == "document-extractor":
        row("inputs", "file", sel(data.get("variable_selector") or []))
    elif t == "list-operator":
        row("inputs", "list", sel(data.get("variable") or []))
    elif t == "variable-aggregator":
        for s in data.get("variables") or []:
            row("inputs", "candidate", sel(s))
    elif t == "assigner":
        for it in data.get("items") or []:
            val = it.get("value")
            row("inputs", f"{it.get('operation')} {sel(it.get('variable_selector') or [])}",
                sel(val) if it.get("input_type") == "variable" and isinstance(val, list) else val)
    elif t == "iteration":
        row("inputs", "for each item of", sel(data.get("iterator_selector") or []))
        row("settings", "collects", sel(data.get("output_selector") or []))
        row("settings", "parallel", f"up to {data.get('parallel_nums')}" if data.get("is_parallel") else "no")
    elif t == "loop":
        row("settings", "max rounds", data.get("loop_count"))
        for v in data.get("loop_variables") or []:
            val = v.get("value")
            row("inputs", f"loop variable {v.get('label')}",
                sel(val) if v.get("value_type") == "variable" and isinstance(val, list) else val)
    elif t == "end":
        for o in data.get("outputs") or []:
            row("outputs", o.get("variable"), sel(o.get("value_selector") or []))
    elif t == "agent":
        row("settings", "strategy", f"{data.get('agent_strategy_provider_name')} › {data.get('agent_strategy_name')}")
        for k, v in (data.get("agent_parameters") or {}).items():
            if k not in ("instruction", "query"):
                row("settings", k, tool_value(v))
    elif t and t.startswith("trigger-"):
        for k in ("mode", "frequency", "cron_expression", "timezone", "method", "content_type", "plugin_id",
                  "event_name"):
            row("settings", k, data.get(k))
        for group in ("headers", "params", "body"):
            for p in data.get(group) or []:
                row("inputs", f"{group} {p.get('name')}", f"{p.get('type')}{', required' if p.get('required') else ''}")
    rc = data.get("retry_config") or {}
    if rc.get("retry_enabled"):
        row("settings", "retry", f"up to {rc.get('max_retries')} times, every {rc.get('retry_interval')} ms")
    if data.get("error_strategy"):
        row("settings", "on error", data.get("error_strategy"))
    return rows


def consumers(dsl):
    """(source node id, field) → ids of nodes that read it."""
    used = defaultdict(set)
    for nid, n in dsl.nodes.items():
        data = dict(n.get("data") or {})
        if not (data.get("vision") or {}).get("enabled"):
            data.pop("vision", None)
        refs = [r.split(".") for _, s in walk_strings(data) for r in REF_RE.findall(s)]
        refs += list(walk_selectors(data))
        ctx = data.get("context") or {}
        if ctx.get("enabled") and ctx.get("variable_selector"):
            refs.append(ctx["variable_selector"])
        for r in refs:
            if len(r) >= 2 and r[0] in dsl.nodes and r[0] != nid:
                used[(r[0], r[1])].add(nid)
    return used


def node_content(dsl, nid, humanize=True):
    """The text that defines what a node does: prompts, code, templates, request bodies."""
    data = dsl.nodes[nid].get("data") or {}
    t = data.get("type")
    blocks = []

    def add(label, text):
        if text and str(text).strip():
            blocks.append({"label": label, "text": humanize_refs(dsl, str(text)) if humanize else str(text)})

    def target_of(handle):
        names = [dsl.title(e["target"]) for e in dsl.out[nid] if (e.get("sourceHandle") or "source") == handle]
        return f" → {', '.join(names)}" if names else " → (not connected)"

    if t == "if-else":
        lines = []
        for i, case in enumerate(data.get("cases") or []):
            joiner = f" {str(case.get('logical_operator', 'and')).upper()} "
            conds = joiner.join(dsl.cond_text(c) for c in case.get("conditions") or []) or "(no condition)"
            lines.append(f"{'IF' if i == 0 else 'ELIF'} {conds}{target_of(case.get('case_id'))}")
        lines.append(f"ELSE{target_of('false')}")
        add("conditions", "\n".join(lines))
    elif t == "question-classifier":
        add("classes → next step", "\n".join(f"{c.get('label') or c.get('name')}: {c.get('name')}{target_of(c.get('id'))}"
                                             for c in data.get("classes") or []))
    elif t == "human-input":
        add("actions → next step", "\n".join(f"{a.get('title')}{target_of(a.get('id'))}"
                                             for a in data.get("user_actions") or []))
    elif t == "loop":
        joiner = f" {str(data.get('logical_operator', 'and')).upper()} "
        add("stop when", joiner.join(dsl.cond_text(c) for c in data.get("break_conditions") or [])
            + f"\n(at most {data.get('loop_count')} rounds)")
        add("loop variables", "\n".join(f"{v.get('label')} ({v.get('var_type')}) starts as {v.get('value')!r}"
                                        for v in data.get("loop_variables") or []))
    elif t == "iteration":
        add("for each", f"item of {dsl.ref_label(data.get('iterator_selector') or ['?'])}\n"
                        f"collects {dsl.ref_label(data.get('output_selector') or ['?'])}"
                        + (f"\nparallel, up to {data.get('parallel_nums')} at once" if data.get("is_parallel") else ""))
    elif t == "start":
        add("inputs", "\n".join(f"{v.get('variable')} ({v.get('type')}{', required' if v.get('required') else ''}):"
                                f" {v.get('label')}" for v in data.get("variables") or []))
    elif t == "end":
        add("outputs", "\n".join(f"{o.get('variable')} = {dsl.ref_label(o.get('value_selector') or ['?'])}"
                                 for o in data.get("outputs") or []))
    elif t == "variable-aggregator":
        add("first non-empty of", "\n".join(dsl.ref_label(s) for s in data.get("variables") or []))
    elif t == "list-operator":
        parts = [f"list: {dsl.ref_label(data.get('variable') or ['?'])}"]
        fb = data.get("filter_by") or {}
        if fb.get("enabled"):
            parts += [f"keep where {c.get('key') or 'item'} {c.get('comparison_operator')} {c.get('value')!r}"
                      for c in fb.get("conditions") or []]
        ob = data.get("order_by") or {}
        if ob.get("enabled"):
            parts.append(f"sort by {ob.get('key') or 'item'} {ob.get('value')}")
        lim = data.get("limit") or {}
        if lim.get("enabled"):
            parts.append(f"take first {lim.get('size')}")
        add("operations", "\n".join(parts))

    if t == "llm":
        pt = data.get("prompt_template")
        for m in (pt if isinstance(pt, list) else [pt or {}]):
            add(f"{m.get('role', 'prompt')} prompt", m.get("jinja2_text") if m.get("edition_type") == "jinja2"
                else m.get("text"))
        if data.get("structured_output_enabled") and data.get("structured_output"):
            add("structured output schema", json.dumps(data["structured_output"].get("schema"), ensure_ascii=False,
                                                         indent=2))
    elif t == "agent":
        for k, v in (data.get("agent_parameters") or {}).items():
            if k in ("instruction", "query") and isinstance(v, dict):
                add(k, v.get("value"))
    elif t in ("question-classifier", "parameter-extractor"):
        add("instruction", data.get("instruction"))
        if t == "question-classifier":
            add("classes", "\n".join(f"- {c.get('name')}" for c in data.get("classes") or []))
        else:
            add("parameters", "\n".join(f"- {p.get('name')} ({p.get('type')}{', required' if p.get('required') else ''})"
                                        f": {p.get('description')}" for p in data.get("parameters") or []))
    elif t == "code":
        add(f"code ({data.get('code_language')})", data.get("code"))
    elif t == "template-transform":
        add("template (jinja2)", data.get("template"))
    elif t == "http-request":
        add("request", f"{str(data.get('method', '')).upper()} {data.get('url')}")
        add("headers", data.get("headers"))
        body = data.get("body") or {}
        items = body.get("data")
        add(f"body ({body.get('type')})", items if isinstance(items, str)
            else "\n".join(i.get("value") or "" for i in items or [] if isinstance(i, dict)))
    elif t == "answer":
        add("answer", data.get("answer"))
    if t == "human-input":
        add("form", data.get("form_content"))
    elif t == "tool":
        add("parameters", "\n".join(f"{k}: {v.get('value') if isinstance(v, dict) else v}"
                                    for k, v in (data.get("tool_parameters") or {}).items()))
    return blocks


def node_brief(dsl, nid):
    """One or two short lines saying what a node does, for diagram boxes."""
    data = dsl.nodes[nid].get("data") or {}
    t = data.get("type")
    fields = lambda xs: ", ".join(xs[:4]) + (" …" if len(xs) > 4 else "")
    if t == "start":
        return [f"inputs: {fields([v.get('variable') for v in data.get('variables') or []])}"] if data.get("variables") else []
    if t == "end":
        return [f"outputs: {fields([o.get('variable') for o in data.get('outputs') or []])}"]
    if t == "answer":
        return [humanize_refs(dsl, data.get("answer") or "")[:60]]
    if t in ("llm", "question-classifier", "parameter-extractor"):
        model = (data.get("model") or {}).get("name")
        extra = []
        if t == "question-classifier":
            extra = [f"{len(data.get('classes') or [])} classes"]
        elif t == "parameter-extractor":
            extra = [f"extracts: {fields([p.get('name') for p in data.get('parameters') or []])}"]
        elif data.get("structured_output_enabled") and data.get("structured_output"):
            props = list(((data["structured_output"].get("schema") or {}).get("properties") or {}).keys())
            extra = [f"JSON: {fields(props)}"]
        return [f"model: {model}"] + extra if model else extra
    if t == "code":
        return [f"→ {fields(list((data.get('outputs') or {}).keys()))}"]
    if t == "if-else":
        cases = data.get("cases") or []
        if not cases:
            return []
        conds = cases[0].get("conditions") or []
        first = dsl.cond_text(conds[0]) if conds else ""
        first = re.sub(r"^\[[^\]]*\]\.", "", first)  # drop the source node title, keep field and comparison
        return [f"if {first}" + (" …" if len(conds) > 1 or len(cases) > 1 else "")]
    if t == "tool":
        return [data.get("tool_label") or data.get("tool_name") or ""]
    if t == "http-request":
        url = re.sub(r"^https?://", "", str(data.get("url") or ""))
        return [f"{str(data.get('method', '')).upper()} {url}"]
    if t == "knowledge-retrieval":
        top_k = (data.get("multiple_retrieval_config") or {}).get("top_k")
        return [f"search knowledge base" + (f", top {top_k}" if top_k else "")]
    if t == "template-transform":
        return ["fills a Jinja2 template"]
    if t == "iteration":
        return [f"for each item of {dsl.ref_label(data.get('iterator_selector') or ['?'])}"]
    if t == "loop":
        return [f"up to {data.get('loop_count')} rounds"]
    if t == "human-input":
        return [f"asks: {fields([a.get('title') for a in data.get('user_actions') or []])}"]
    if t == "agent":
        return [f"agent: {data.get('agent_strategy_name')}"]
    return []


# Content blocks already shown as field rows on a node page (graph JSON drops them to avoid repetition).
COVERED_BY_FIELDS = {("tool", "parameters"), ("http-request", "request"), ("http-request", "headers"),
                     ("start", "inputs"), ("end", "outputs"), ("iteration", "for each")}


def graph_json(dsl):
    """Nodes and edges for a diagram. Internal start nodes are folded into their container."""
    internal = {i for i in dsl.nodes if dsl.dtype(i) in INTERNAL_TYPES}
    order = dsl.order([i for i in dsl.nodes if not dsl.nodes[i].get("parentId")])
    i = 0
    while i < len(order):  # append container bodies, including nested containers
        order += [c for c in dsl.order(dsl.children.get(order[i], [])) if c not in order]
        i += 1
    used = consumers(dsl)
    nodes = []
    for nid in order:
        t = dsl.dtype(nid)
        details = summarize_node(dsl, nid)
        reads = dsl.inputs_of(nid) if t != "end" else []
        if reads:
            details.append(f"reads: {', '.join(reads)}")
        used_by = {f: sorted(c, key=order.index) for (src, f), c in used.items() if src == nid}
        nodes.append({"id": nid, "type": t, "category": DISPLAY_CATEGORY.get(t, "other"),
                      "title": dsl.title(nid), "parent": dsl.nodes[nid].get("parentId"),
                      "portability": PORTABILITY.get(t, "unknown"), "details": details,
                      "brief": node_brief(dsl, nid),
                      "fields": node_fields(dsl, nid), "used_by": used_by,
                      "content": [b for b in node_content(dsl, nid, humanize=False)
                                  if (t, b["label"]) not in COVERED_BY_FIELDS
                                  and not (t == "http-request" and b["label"].startswith("body"))]})
    env = {e.get("name"): e.get("value_type") for e in dsl.workflow.get("environment_variables") or []}
    edges = []
    for e in dsl.edges:
        src, dst = e.get("source"), e.get("target")
        if src not in dsl.nodes or dst not in dsl.nodes or dst in internal:
            continue
        if src in internal:  # container start → first body node
            edges.append({"from": dsl.nodes[src].get("parentId"), "to": dst, "label": "body"})
            continue
        edges.append({"from": src, "to": dst, "label": dsl.branch_label(src, e.get("sourceHandle"))})
    notes = []
    for n in dsl.notes:
        text = (n.get("data") or {}).get("text") or ""
        notes.append(" ".join(re.findall(r'"text":"((?:[^"\\]|\\.)*)"', text)) or text)
    return {"name": dsl.app.get("name"), "mode": dsl.app.get("mode"),
            "description": dsl.app.get("description") or "", "nodes": nodes, "edges": edges, "notes": notes,
            "env": env}


def slugify(text, fallback):
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return s or fallback


PY_HARNESS = '''

if __name__ == "__main__":
    # Reads the node inputs as a JSON object on stdin and prints main()'s result as JSON.
    import json as _json
    import sys as _sys
    print(_json.dumps(main(**_json.load(_sys.stdin)), ensure_ascii=False))
'''
JS_HARNESS = '''

// Reads the node inputs as a JSON object on stdin and prints main()'s result as JSON.
let __input = "";
process.stdin.on("data", (d) => (__input += d)).on("end", () => {
  console.log(JSON.stringify(main(JSON.parse(__input || "{}"))));
});
'''


def extract_code(dsl, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    used = set()
    for nid in dsl.order(list(dsl.nodes)):
        data = dsl.nodes[nid].get("data") or {}
        if data.get("type") != "code":
            continue
        lang = data.get("code_language")
        ext = ".js" if lang == "javascript" else ".py"
        base = slugify(data.get("title"), f"node_{slugify(nid, 'code')}")
        name, i = base, 2
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        comment = "//" if ext == ".js" else "#"
        header = f"{comment} Converted from Dify code node \"{data.get('title')}\" (id: {nid}).\n"
        body = (data.get("code") or "").rstrip() + (JS_HARNESS if ext == ".js" else PY_HARNESS)
        target = out_dir / f"{name}{ext}"
        target.write_text(header + body, encoding="utf-8")
        ins = ", ".join(v.get("variable", "?") for v in data.get("variables") or [])
        outs = ", ".join((data.get("outputs") or {}).keys())
        print(f"{target}  ←  {dsl.title(nid)}  (stdin JSON keys: {ins}; output keys: {outs})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dsl")
    ap.add_argument("--node", help="print the full data of one node")
    ap.add_argument("--extract-code", metavar="DIR", help="write code nodes as runnable scripts into DIR")
    ap.add_argument("--graph-json", action="store_true", help="print nodes and edges as JSON for diagrams")
    ap.add_argument("--content", action="store_true",
                    help="print every node's prompts / code / templates in execution order, references made readable")
    args = ap.parse_args()
    try:
        data = yaml.safe_load(Path(args.dsl).read_text(encoding="utf-8"))
        assert isinstance(data, dict)
    except Exception as e:  # noqa: BLE001 - report any unreadable input the same way
        print(f"Cannot read DSL: {e}", file=sys.stderr)
        return 2
    dsl = Dsl(data)
    if args.node:
        print(node_detail(dsl, args.node))
    elif args.extract_code:
        extract_code(dsl, args.extract_code)
    elif args.graph_json:
        print(json.dumps(graph_json(dsl), ensure_ascii=False, indent=1))
    elif args.content:
        for n in graph_json(dsl)["nodes"]:
            if not n["content"]:
                continue
            print(f"## {n['title']} — `{n['type']}` (id: `{n['id']}`)\n")
            for b in n["content"]:
                print(f"**{b['label']}**\n\n````\n{b['text'].rstrip()}\n````\n")
    else:
        print(overview(dsl, args.dsl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
