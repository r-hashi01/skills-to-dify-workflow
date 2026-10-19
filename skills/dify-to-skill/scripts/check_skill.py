# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Check a skill folder generated from a Dify DSL.

Usage: uv run check_skill.py <skill-dir>

Checks: SKILL.md frontmatter (name matches folder, kebab-case; description present),
SKILL.md under 500 lines, relative links resolve, no leftover Dify template syntax,
scripts compile (python3 / node --check), no secret-looking literals.
Exit code: 0 = no errors (warnings allowed), 1 = errors, 2 = not a skill folder.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
DIFY_REF_RE = re.compile(r"\{\{#[^#}]+#\}\}")
SECRET_RES = [
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),          # Slack
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),                 # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),            # GitHub
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                    # AWS
    re.compile(r"\bapp-[A-Za-z0-9]{20,}"),                  # Dify app key
    re.compile(r"\bdataset-[A-Za-z0-9]{20,}"),              # Dify dataset key
    re.compile(r"Bearer\s+(?!\$|\{|<)[A-Za-z0-9._-]{20,}"),  # literal bearer token
]
TEXT_SUFFIXES = {".md", ".py", ".js", ".sh", ".txt", ".json", ".yaml", ".yml", ".j2", ".html", ""}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        print(f"not a skill folder (no SKILL.md): {root}", file=sys.stderr)
        return 2

    errors, warnings = [], []
    text = skill_md.read_text(encoding="utf-8")

    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if not match:
        errors.append("SKILL.md: missing YAML frontmatter")
    else:
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as e:
            errors.append(f"SKILL.md: invalid frontmatter YAML: {e}")
    name, desc = meta.get("name"), meta.get("description")
    if not name:
        errors.append("frontmatter: `name` missing")
    elif not NAME_RE.match(str(name)):
        errors.append(f"frontmatter: name `{name}` is not kebab-case ASCII")
    elif name != root.name:
        errors.append(f"frontmatter: name `{name}` does not match folder `{root.name}`")
    if not desc:
        errors.append("frontmatter: `description` missing")
    elif len(str(desc)) > 1024:
        warnings.append(f"frontmatter: description is {len(str(desc))} chars (keep it under 1024)")

    lines = text.count("\n") + 1
    if lines > 500:
        errors.append(f"SKILL.md: {lines} lines (limit 500); move detail into references/")

    files = [p for p in root.rglob("*") if p.is_file()]
    for f in files:
        rel = f.relative_to(root)
        if f.suffix not in TEXT_SUFFIXES:
            continue
        try:
            body = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if f.suffix == ".md":
            for target in LINK_RE.findall(body):
                if re.match(r"^[a-z]+:", target):
                    continue
                if not (f.parent / target).exists():
                    errors.append(f"{rel}: broken link `{target}`")
        if f.suffix in {".md", ".j2", ".txt"} and DIFY_REF_RE.search(body):
            errors.append(f"{rel}: Dify template syntax left: `{DIFY_REF_RE.search(body).group(0)}`")
        for pat in SECRET_RES:
            hit = pat.search(body)
            if hit:
                errors.append(f"{rel}: secret-looking literal `{hit.group(0)[:12]}…`")

        if f.suffix == ".py":
            try:
                compile(body, str(rel), "exec")  # syntax only; nothing is executed or written
            except SyntaxError as e:
                errors.append(f"{rel}: Python syntax error at line {e.lineno}: {e.msg}")
        elif f.suffix == ".js":
            if shutil.which("node"):
                r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
                if r.returncode:
                    errors.append(f"{rel}: JavaScript syntax error: {r.stderr.strip().splitlines()[0]}")
            else:
                warnings.append(f"{rel}: node not installed; JavaScript not checked")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{root.name}: {len(errors)} error(s), {len(warnings)} warning(s), {len(files)} file(s), SKILL.md {lines} lines")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
