# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#   "graphon==0.7.0",
#   "pydantic>=2.7",
#   "pyyaml>=6",
#   "jsonschema>=4",
#   "httpx>=0.28",
#   "charset-normalizer>=2.1",
# ]
#
# [tool.uv]
# # graphon's runtime extras (document parsing, tokenizers, ML) are not needed to
# # validate node schemas. Disable them so the environment stays ~20MB instead of ~600MB.
# override-dependencies = [
#   "pandas; sys_platform == 'never'",
#   "transformers; sys_platform == 'never'",
#   "unstructured; sys_platform == 'never'",
#   "tiktoken; sys_platform == 'never'",
#   "pypdf; sys_platform == 'never'",
#   "pypdfium2; sys_platform == 'never'",
#   "python-docx; sys_platform == 'never'",
#   "pypandoc; sys_platform == 'never'",
#   "webvtt-py; sys_platform == 'never'",
#   "json-repair; sys_platform == 'never'",
#   "orjson; sys_platform == 'never'",
#   "pydantic-extra-types; sys_platform == 'never'",
# ]
# ///
"""Validate core-node data in a Dify DSL YAML against graphon's schemas, and upgrade legacy shapes.

Usage:
  uv run validate_dsl.py <workflow.yml>                      Validate; report legacy shapes
  uv run validate_dsl.py <workflow.yml> --fix [-o OUT.yml]   Upgrade legacy shapes, write OUT.yml
                                                             (default <name>.fixed.yml), then validate it

Scope: only core nodes defined by graphon are schema-validated. Dify-specific nodes
(triggers, knowledge-retrieval, agent, human-input, custom-note, ...) are listed
as skipped. Graph structure, edges, and security are NOT covered here.

Legacy upgrades follow what Dify's editor does when it opens and saves an app
(web/app/components/workflow/utils/workflow-init.ts) plus runtime gaps it never fixes.

Exit code: 0 = all core nodes valid and nothing breaking left, 1 = validation errors or
breaking legacy shapes, 2 = unreadable input.
"""

import argparse
import copy
import importlib
import importlib.util
import pathlib
import sys
import types

import yaml
from pydantic import ValidationError

CURRENT_DSL_VERSION = "0.7.0"

# type -> (module under graphon.nodes, entity class)
CORE_NODES = {
    "start": ("start.entities", "StartNodeData"),
    "end": ("end.entities", "EndNodeData"),
    "answer": ("answer.entities", "AnswerNodeData"),
    "llm": ("llm.entities", "LLMNodeData"),
    "tool": ("tool.entities", "ToolNodeData"),
    "code": ("code.entities", "CodeNodeData"),
    "template-transform": ("template_transform.entities", "TemplateTransformNodeData"),
    "if-else": ("if_else.entities", "IfElseNodeData"),
    "question-classifier": ("question_classifier.entities", "QuestionClassifierNodeData"),
    "parameter-extractor": ("parameter_extractor.entities", "ParameterExtractorNodeData"),
    "document-extractor": ("document_extractor.entities", "DocumentExtractorNodeData"),
    "list-operator": ("list_operator.entities", "ListOperatorNodeData"),
    "variable-aggregator": ("variable_aggregator.entities", "VariableAggregatorNodeData"),
    "assigner": ("variable_assigner.v2.entities", "VariableAssignerNodeData"),
    "iteration": ("iteration.entities", "IterationNodeData"),
    "iteration-start": ("iteration.entities", "IterationStartNodeData"),
    "loop": ("loop.entities", "LoopNodeData"),
    "loop-start": ("loop.entities", "LoopStartNodeData"),
    "loop-end": ("loop.entities", "LoopEndNodeData"),
    "http-request": ("http_request.entities", "HttpRequestNodeData"),
}
# assigner v1 (assigned_variable_selector / write_mode) still runs; validate it with its own model
ASSIGNER_V1 = ("variable_assigner.v1.node_data", "VariableAssignerData")
PLUGIN_NODE_TYPES = {"llm", "question-classifier", "parameter-extractor", "tool", "agent", "knowledge-retrieval"}


# ---------------------------------------------------------------- legacy upgrades


class Upgrader:
    """Apply legacy-shape upgrades in place and record what changed.

    `breaking` entries fail at import or run time in current Dify; `upgrades` are
    shapes current Dify tolerates but only normalizes when the editor saves.
    """

    def __init__(self, dsl: dict):
        self.dsl = dsl
        graph = (dsl.get("workflow") or {}).get("graph") or {}
        self.nodes = graph.setdefault("nodes", [])
        self.edges = graph.setdefault("edges", [])
        self.breaking: list[str] = []
        self.upgrades: list[str] = []
        self.warnings: list[str] = []

    def label(self, node: dict) -> str:
        data = node.get("data") or {}
        return f"{node.get('id')} ({data.get('title') or data.get('type')})"

    def run(self) -> "Upgrader":
        by_id = {n.get("id"): n for n in self.nodes}
        for node in list(self.nodes):
            data = node.get("data")
            if not isinstance(data, dict):
                continue
            t = data.get("type")
            if t == "variable-assigner":
                data["type"] = "variable-aggregator"
                for e in self.edges:
                    ed = e.get("data") or {}
                    for k in ("sourceType", "targetType"):
                        if ed.get(k) == "variable-assigner":
                            ed[k] = "variable-aggregator"
                self.breaking.append(f"{self.label(node)}: legacy type `variable-assigner` → `variable-aggregator` "
                                     "(no runtime class is registered for the old name)")
            elif t == "assigner" and "items" in data and str(data.get("version", "1")) != "2":
                data["version"] = "2"
                self.breaking.append(f"{self.label(node)}: assigner with `items` but no version '2' → set version '2' "
                                     "(otherwise it is parsed as v1 and fails)")
            elif t == "if-else" and not data.get("cases") and data.get("conditions") is not None:
                data["cases"] = [{"case_id": "true", "id": "true",
                                  "logical_operator": data.get("logical_operator") or "and",
                                  "conditions": data["conditions"]}]
                data.pop("conditions", None)
                data.pop("logical_operator", None)
                self.upgrades.append(f"{self.label(node)}: if-else top-level `conditions` → `cases`")
            elif t == "http-request":
                body = data.get("body")
                if isinstance(body, dict) and not isinstance(body.get("data"), list):
                    raw = body.get("data")
                    body["data"] = [{"key": "", "type": "text", "value": raw}] if raw else []
                    self.upgrades.append(f"{self.label(node)}: http body `data` string → list")
                if not data.get("retry_config"):
                    data["retry_config"] = {"retry_enabled": True, "max_retries": 3, "retry_interval": 100}
                    self.upgrades.append(f"{self.label(node)}: added editor-default retry_config (3 retries)")
            elif t == "parameter-extractor":
                for p in data.get("parameters") or []:
                    new = {"bool": "boolean", "select": "string"}.get(p.get("type"))
                    if new:
                        self.upgrades.append(f"{self.label(node)}: parameter `{p.get('name')}` type "
                                             f"`{p['type']}` → `{new}`")
                        p["type"] = new
            elif t == "end":
                for o in data.get("outputs") or []:
                    vt = o.get("value_type")
                    if isinstance(vt, str) and vt.startswith("Array["):
                        o["value_type"] = vt.lower()
                        self.upgrades.append(f"{self.label(node)}: output `{o.get('variable')}` value_type "
                                             f"`{vt}` → `{vt.lower()}`")
            elif t == "tool" and not data.get("version") and not data.get("tool_node_version"):
                data["tool_node_version"] = "2"
                confs = data.get("tool_configurations") or {}
                for k, v in list(confs.items()):
                    if not isinstance(v, dict):
                        confs[k] = {"type": "constant", "value": v}
                self.upgrades.append(f"{self.label(node)}: tool parameters → tool_node_version '2' format")
            if t in ("iteration", "loop"):
                self._ensure_container_start(node, by_id)

        for e in self.edges:
            fixed = []
            if not e.get("sourceHandle"):
                e["sourceHandle"] = "source"
                fixed.append("sourceHandle")
            if not e.get("targetHandle"):
                e["targetHandle"] = "target"
                fixed.append("targetHandle")
            if fixed:
                self.upgrades.append(f"edge {e.get('source')} → {e.get('target')}: filled default {', '.join(fixed)}")

        self._check_version()
        self._check_dependencies()
        for node in self.nodes:
            data = node.get("data") or {}
            if data.get("type") == "knowledge-retrieval" and data.get("dataset_ids"):
                self.warnings.append(f"{self.label(node)}: dataset_ids must exist in the target workspace; IDs from "
                                     "another Dify instance are silently dropped on import")
        return self

    def _ensure_container_start(self, node: dict, by_id: dict) -> None:
        data = node["data"]
        kind = data["type"]
        start_type = f"custom-{kind}-start"
        current = by_id.get(data.get("start_node_id"))
        if current is not None and current.get("type") == start_type:
            return
        start_id = f"{node['id']}start"
        i = 0
        while start_id in by_id:
            start_id = f"{node['id']}start{i}"
            i += 1
        flag = "isInIteration" if kind == "iteration" else "isInLoop"
        start = {
            "id": start_id, "type": start_type, "parentId": node["id"],
            "position": {"x": 24, "y": 68}, "positionAbsolute": {"x": 24, "y": 68},
            "width": 44, "height": 48, "zIndex": 1002, "selectable": False, "draggable": False,
            "data": {"type": f"{kind}-start", "title": "", "desc": "", flag: True},
        }
        self.nodes.append(start)
        by_id[start_id] = start
        if current is not None:
            parent_key = "iteration_id" if kind == "iteration" else "loop_id"
            self.edges.append({
                "id": f"{start_id}-source-{current['id']}-target", "type": "custom",
                "source": start_id, "sourceHandle": "source", "target": current["id"], "targetHandle": "target",
                "zIndex": 1002,
                "data": {"sourceType": f"{kind}-start", "targetType": (current.get("data") or {}).get("type"),
                         flag: True, parent_key: node["id"]},
            })
        data["start_node_id"] = start_id
        if kind == "iteration":
            data.setdefault("is_parallel", False)
            data.setdefault("parallel_nums", 10)
            data.setdefault("error_handle_mode", "terminated")
        self.upgrades.append(f"{self.label(node)}: added `{start_type}` child node `{start_id}`")

    def _check_version(self) -> None:
        raw = str(self.dsl.get("version") or "0.1.0")
        try:
            ver = tuple(int(x) for x in raw.split("."))
            cur = tuple(int(x) for x in CURRENT_DSL_VERSION.split("."))
        except ValueError:
            self.warnings.append(f"DSL version `{raw}` is not a valid version string")
            return
        if ver > cur:
            self.warnings.append(f"DSL version {raw} is newer than {CURRENT_DSL_VERSION}; this validator may be outdated")
        elif ver < cur:
            self.dsl["version"] = CURRENT_DSL_VERSION
            self.upgrades.append(f"DSL version {raw} → {CURRENT_DSL_VERSION}")

    def _check_dependencies(self) -> None:
        if self.dsl.get("dependencies"):
            return
        providers = set()
        for node in self.nodes:
            data = node.get("data") or {}
            t = data.get("type")
            if t not in PLUGIN_NODE_TYPES:
                continue
            p = (data.get("model") or {}).get("provider") or data.get("provider_id") \
                or data.get("agent_strategy_provider_name")
            if p and "/" in p:
                providers.add("/".join(p.split("/")[:2]))
        if providers:
            self.warnings.append("no `dependencies` listed, but the graph uses plugins: "
                                 f"{', '.join(sorted(providers))}. Self-hosted Dify without the marketplace will not "
                                 "prompt to install them")


# ---------------------------------------------------------------- schema validation


def _skip_node_package_inits() -> None:
    """Register graphon.nodes.* packages without running their __init__.py.

    Each node package's __init__ imports the runtime node implementation, which
    pulls in the heavy dependencies disabled above. The entities modules don't
    need them.
    """
    spec = importlib.util.find_spec("graphon")
    root = pathlib.Path(spec.submodule_search_locations[0])
    for init in sorted((root / "nodes").rglob("__init__.py")):
        name = ".".join(init.parent.relative_to(root.parent).parts)
        module = types.ModuleType(name)
        module.__path__ = [str(init.parent)]
        sys.modules[name] = module


def _model_for(data: dict):
    node_type = data.get("type")
    if node_type == "assigner" and str(data.get("version", "1")) != "2":
        module_name, class_name = ASSIGNER_V1
    elif node_type in CORE_NODES:
        module_name, class_name = CORE_NODES[node_type]
    else:
        return None
    return getattr(importlib.import_module(f"graphon.nodes.{module_name}"), class_name)


def _format_errors(error: ValidationError) -> list[str]:
    lines = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"{loc}: {item['msg']}")
    return lines


def validate(nodes: list) -> int:
    _skip_node_package_inits()
    failed = valid = 0
    skipped: list[str] = []
    for node in nodes:
        data = node.get("data") or {}
        node_type = data.get("type")
        label = f"{node.get('id')} ({data.get('title') or node_type or node.get('type')})"
        model = _model_for(data)
        if model is None:
            skipped.append(f"{label}: {node_type or node.get('type')}")
            continue
        try:
            model.model_validate(data)
            valid += 1
        except ValidationError as e:
            failed += 1
            print(f"FAIL {label} [{node_type}]")
            for line in _format_errors(e):
                print(f"     {line}")
    if skipped:
        print("SKIPPED (not a graphon core node; check manually):")
        for line in skipped:
            print(f"     {line}")
    print(f"core nodes: {valid} valid, {failed} invalid; skipped: {len(skipped)}")
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dsl")
    ap.add_argument("--fix", action="store_true", help="upgrade legacy shapes and write the result")
    ap.add_argument("-o", "--output", help="output path for --fix (default: <name>.fixed.yml next to the input)")
    args = ap.parse_args()
    src = pathlib.Path(args.dsl)
    try:
        dsl = yaml.safe_load(src.read_text(encoding="utf-8"))
        nodes = dsl["workflow"]["graph"]["nodes"]
        assert isinstance(nodes, list)
    except (OSError, yaml.YAMLError, KeyError, TypeError, AssertionError) as e:
        print(f"Cannot read workflow.graph.nodes: {e}", file=sys.stderr)
        return 2

    target = dsl if args.fix else copy.deepcopy(dsl)
    up = Upgrader(target).run()

    if args.fix:
        for line in up.breaking + up.upgrades:
            print(f"FIXED {line}")
        out = pathlib.Path(args.output) if args.output else src.with_name(f"{src.stem}.fixed{src.suffix or '.yml'}")
        out.write_text(yaml.safe_dump(target, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        print(f"wrote {out} ({len(up.breaking) + len(up.upgrades)} change(s))")
    else:
        for line in up.breaking:
            print(f"LEGACY (breaks in current Dify; fix with --fix) {line}")
        for line in up.upgrades:
            print(f"LEGACY (tolerated; normalize with --fix) {line}")
    for line in up.warnings:
        print(f"WARN  {line}")

    failed = validate((target if args.fix else dsl)["workflow"]["graph"]["nodes"])
    breaking_left = 0 if args.fix else len(up.breaking)
    return 1 if failed or breaking_left else 0


if __name__ == "__main__":
    sys.exit(main())
