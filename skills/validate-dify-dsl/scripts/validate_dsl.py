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
"""Validate core-node data in a Dify DSL YAML against graphon's schemas.

Usage: uv run validate_dsl.py <workflow.yml>  (wrapped by the validate-dify-dsl skill)

Scope: only core nodes defined by graphon are validated. Dify-specific nodes
(triggers, knowledge-retrieval, agent, human-input, custom-note, ...) are listed
as skipped. Graph structure, edges, and security checks are NOT covered here.

Exit code: 0 = all core nodes valid, 1 = validation errors, 2 = unreadable input.
"""

import importlib
import importlib.util
import pathlib
import sys
import types

import yaml
from pydantic import ValidationError

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


def _format_errors(error: ValidationError) -> list[str]:
    lines = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"{loc}: {item['msg']}")
    return lines


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: uv run validate_dsl.py <workflow.yml>", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            dsl = yaml.safe_load(f)
        nodes = dsl["workflow"]["graph"]["nodes"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as e:
        print(f"Cannot read workflow.graph.nodes: {e}", file=sys.stderr)
        return 2

    _skip_node_package_inits()

    failed = valid = 0
    skipped: list[str] = []
    for node in nodes:
        data = node.get("data") or {}
        node_type = data.get("type")
        label = f"{node.get('id')} ({data.get('title') or node_type or node.get('type')})"
        if node_type not in CORE_NODES:
            skipped.append(f"{label}: {node_type or node.get('type')}")
            continue
        module_name, class_name = CORE_NODES[node_type]
        model = getattr(importlib.import_module(f"graphon.nodes.{module_name}"), class_name)
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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
