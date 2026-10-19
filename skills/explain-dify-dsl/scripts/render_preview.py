"""Render a Dify workflow as a self-contained, DeepWiki-style HTML page.

Usage:
  uv run ../dify-to-skill/scripts/analyze_dsl.py app.yml --graph-json \
    | python3 render_preview.py - --explanation explanation.md --lang ja -o app-explained.html

  graph          JSON from analyze_dsl.py --graph-json ('-' for stdin)
  --explanation  Markdown written by Claude. Each top-level "# Heading" starts a page in the sidebar.
                 [[node_id]] or [[node_id › field]] become links to node pages; a line containing only
                 [[diagram]] places a diagram of the nodes the page mentions.
  --lang         Language of the page chrome: ja (default) or en

The page has concept pages (from the explanation), a full flow map, and one generated reference page
per node (inputs, settings, branches, where outputs are used, full prompt / code). Standard library only.
All DSL-derived text and the explanation are inserted with DOM APIs, never as HTML, because they come
from an untrusted file.
"""

import argparse
import json
import re
import sys
from pathlib import Path

UI_TEXT = {
    "ja": {
        "overview": "概要", "map": "全体図", "nodes": "ノード", "on_this_page": "このページの内容",
        "inputs": "入力", "settings": "設定", "outputs": "出力", "branches": "分岐", "used_by": "出力の使われ先",
        "next": "次のステップ", "prev": "前のステップ", "content": "中身", "mentioned_in": "このノードを説明しているページ",
        "related": "関係するノード", "field": "項目", "value": "値", "condition": "条件",
        "goes_to": "進む先", "used_in": "使われる先", "not_used": "(後続で使われていない)", "neighborhood": "前後のつながり",
        "secret": "シークレット", "fixed": "固定値", "click_hint": "ノードをクリックすると、そのノードのページを開きます。",
        "no_explanation": "解説はまだありません。全体図とノードのページを参照してください。",
        "context": "ナレッジ検索の結果", "else": "それ以外", "start": "開始", "type": "種類",
    },
    "en": {
        "overview": "Overview", "map": "Flow map", "nodes": "Nodes", "on_this_page": "On this page",
        "inputs": "Inputs", "settings": "Settings", "outputs": "Outputs", "branches": "Branches", "used_by": "Where outputs are used",
        "next": "Next steps", "prev": "Previous steps", "content": "Content", "mentioned_in": "Explained in",
        "related": "Related nodes", "field": "Field", "value": "Value", "condition": "Condition",
        "goes_to": "Goes to", "used_in": "Used by", "not_used": "(not used downstream)", "neighborhood": "Connections",
        "secret": "secret", "fixed": "fixed value", "click_hint": "Click a node to open its page.",
        "no_explanation": "No written explanation yet. See the flow map and the node pages.",
        "context": "knowledge retrieval result", "else": "Otherwise", "start": "Start", "type": "Type",
    },
}

TEMPLATE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #ffffff; --fg: #1f2328; --muted: #656d76; --line: #8c959f; --panel: #f6f8fa; --border: #d0d7de;
  --code-bg: #eff1f3; --accent: #0969da; --warn-bg: #fff8c5; --warn-fg: #7d4e00; --active: #ddf4ff;
  --start-bg: #F3F4F6; --start-bd: #9CA3AF; --end-bg: #F3F4F6; --end-bd: #9CA3AF;
  --llm-bg: #EDE9FE; --llm-bd: #7C3AED; --tool-bg: #DBEAFE; --tool-bd: #2563EB;
  --condition-bg: #FEF3C7; --condition-bd: #D97706; --loop-bg: #FFEDD5; --loop-bd: #EA580C;
  --template-bg: #D1FAE5; --template-bd: #059669; --human-bg: #FCE7F3; --human-bd: #DB2777;
  --other-bg: #F3F4F6; --other-bd: #6B7280;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d1117; --fg: #e6edf3; --muted: #8d96a0; --line: #6e7681; --panel: #161b22; --border: #30363d;
    --code-bg: #262c36; --accent: #4493f8; --warn-bg: #3b2e0a; --warn-fg: #e3b341; --active: #172a45;
    --start-bg: #262a30; --end-bg: #262a30; --llm-bg: #2e2448; --tool-bg: #1c2b45; --condition-bg: #3a2d12;
    --loop-bg: #3b2414; --template-bg: #12342a; --human-bg: #3a1a2b; --other-bg: #262a30;
  }
}
:root[data-theme="dark"] {
  --bg: #0d1117; --fg: #e6edf3; --muted: #8d96a0; --line: #6e7681; --panel: #161b22; --border: #30363d;
  --code-bg: #262c36; --accent: #4493f8; --warn-bg: #3b2e0a; --warn-fg: #e3b341; --active: #172a45;
  --start-bg: #262a30; --end-bg: #262a30; --llm-bg: #2e2448; --tool-bg: #1c2b45; --condition-bg: #3a2d12;
  --loop-bg: #3b2414; --template-bg: #12342a; --human-bg: #3a1a2b; --other-bg: #262a30;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--fg); }
body { font: 15px/1.75 system-ui, -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.shell { display: grid; grid-template-columns: 260px minmax(0, 1fr) 220px; min-height: 100vh; }
@media (max-width: 1180px) { .shell { grid-template-columns: 240px minmax(0, 1fr); } .toc { display: none; } }
@media (max-width: 780px) { .shell { grid-template-columns: minmax(0, 1fr); } .side { position: static !important; height: auto !important; border-right: 0 !important; border-bottom: 1px solid var(--border); } }
.side { position: sticky; top: 0; height: 100vh; overflow: auto; border-right: 1px solid var(--border); background: var(--panel); padding: 18px 14px; }
.side .app { font-weight: 700; font-size: 15px; line-height: 1.4; margin: 0 4px 2px; }
.side .mode { color: var(--muted); font-size: 12px; margin: 0 4px 14px; }
.side h3 { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin: 18px 4px 6px; }
.side a { display: flex; gap: 8px; align-items: center; padding: 4px 8px; border-radius: 6px; color: var(--fg); font-size: 14px; line-height: 1.45; }
.side a:hover { background: var(--active); text-decoration: none; }
.side a.active { background: var(--active); font-weight: 600; }
.side a.child { padding-left: 24px; }
.dot { flex: none; width: 9px; height: 9px; border-radius: 3px; background: var(--c-bg); border: 1.5px solid var(--c-bd); }
main { min-width: 0; padding: 28px 40px 80px; }
@media (max-width: 780px) { main { padding: 20px 16px 60px; } }
.content { max-width: 880px; }
.toc { position: sticky; top: 0; height: 100vh; overflow: auto; padding: 28px 16px; font-size: 13px; }
.toc h4 { margin: 0 0 8px; font-size: 12px; color: var(--muted); }
.toc a { display: block; color: var(--muted); padding: 3px 0 3px 10px; border-left: 2px solid var(--border); line-height: 1.45; }
.toc a:hover { color: var(--fg); }
.crumb { color: var(--muted); font-size: 13px; margin-bottom: 4px; }
h1.page { font-size: 28px; line-height: 1.3; margin: 0 0 8px; }
.badge { display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--c-bd); background: var(--c-bg); color: var(--fg); vertical-align: middle; margin-right: 6px; }
.lead { color: var(--muted); margin: 0 0 20px; }
.content h2 { font-size: 21px; line-height: 1.4; margin: 2em 0 .6em; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.content h3 { font-size: 17px; margin: 1.6em 0 .5em; }
.content h4 { font-size: 15px; margin: 1.4em 0 .4em; }
.content p, .content ul, .content ol, .content blockquote, .content table, .content pre, .content figure { margin: 0 0 1em; }
.content ul, .content ol { padding-left: 1.5em; }
.content li { margin: .25em 0; }
.content blockquote { margin-left: 0; padding: 6px 16px; border-left: 4px solid var(--border); background: var(--panel); border-radius: 0 6px 6px 0; }
.content table { border-collapse: collapse; width: 100%; display: block; overflow-x: auto; font-size: 14px; }
.content th, .content td { border: 1px solid var(--border); padding: 7px 11px; text-align: left; vertical-align: top; }
.content th { background: var(--panel); white-space: nowrap; }
.content td.name { white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
code { font: .86em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: var(--code-bg); padding: .12em .38em; border-radius: 4px; overflow-wrap: anywhere; }
pre { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre code { background: none; padding: 0; font-size: inherit; }
.block-label { font-size: 13px; font-weight: 600; color: var(--muted); margin: 1.2em 0 .4em; }
.chip { display: inline-flex; align-items: center; gap: 5px; padding: 0 7px; margin: 1px 1px; border-radius: 6px; border: 1px solid var(--c-bd, var(--border)); background: var(--c-bg, var(--panel)); color: var(--fg); font: 12.5px/1.7 system-ui, -apple-system, "Hiragino Sans", sans-serif; white-space: nowrap; vertical-align: baseline; }
.chip:hover { text-decoration: none; filter: brightness(0.96); }
.chip .f { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: var(--muted); }
.chip.plain { --c-bg: var(--panel); --c-bd: var(--border); }
.warn { background: var(--warn-bg); color: var(--warn-fg); border-radius: 4px; padding: 0 4px; }
figure.diagram { border: 1px solid var(--border); border-radius: 10px; padding: 8px; overflow: auto; background: var(--bg); }
figure.diagram svg { display: block; margin: 0 auto; max-width: 100%; height: auto; }  /* shrink wide diagrams to fit */
figure.diagram figcaption { color: var(--muted); font-size: 12px; text-align: center; margin-top: 4px; }
svg text { fill: var(--fg); font-size: 12px; }
svg .node { cursor: pointer; }
svg .node rect { stroke-width: 1.5; }
svg .node.here rect { stroke-width: 3.5; }
svg .node .title { font-size: 13px; font-weight: 600; }
svg .node .detail { font-size: 11.5px; }
svg .node .sub { fill: var(--muted); font-size: 10px; }
svg .edge { fill: none; stroke: var(--line); stroke-width: 1.5; }
svg.focus .edge:not(.hl) { opacity: .15; }
svg.focus .elabel:not(.hl) { opacity: .2; }
svg .edge.hl { stroke: var(--fg); stroke-width: 2.25; }
svg .elabel rect { fill: var(--panel); stroke: var(--border); }
svg .elabel text { font-size: 10px; fill: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.pager { display: flex; justify-content: space-between; gap: 12px; margin-top: 3em; }
.pager a { border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; font-size: 14px; }
</style>
</head>
<body>
<div class="shell">
  <nav class="side" id="side"></nav>
  <main><div class="content" id="content"></div></main>
  <aside class="toc" id="toc"></aside>
</div>
<script id="graph-data" type="application/json">__DATA__</script>
<script id="explanation-data" type="application/json">__EXPLANATION__</script>
<script>
(function () {
  "use strict";
  const g = JSON.parse(document.getElementById("graph-data").textContent);
  const md = JSON.parse(document.getElementById("explanation-data").textContent);
  const T = g.ui;
  const NS = "http://www.w3.org/2000/svg";
  const W = 260, COL = 290, GAP = 56, MARGIN = 24, MAXROW = 3, LANE = 160;
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  const order = Object.fromEntries(g.nodes.map((n, i) => [n.id, i]));

  // ---------- DOM helpers ----------
  const h = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  };
  const sv = (name, attrs, parent) => {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };
  const clip = (s, n) => {  // by display width: full-width characters count as 2
    let w = 0, out = "";
    for (const ch of String(s)) { w += /[ᄀ-￿]/.test(ch) ? 2 : 1; if (w > n) return out + "…"; out += ch; }
    return out;
  };
  const catStyle = (e, cat) => { e.style.setProperty("--c-bg", `var(--${cat}-bg)`); e.style.setProperty("--c-bd", `var(--${cat}-bd)`); };
  const slug = (s, i) => "p" + i;

  // ---------- references → chips ----------
  function chip(nodeId, field) {
    if (nodeId === "env") {
      const c = h("span", "chip plain"); const secret = g.env && g.env[field] === "secret";
      c.appendChild(h("span", "", "env")); c.appendChild(h("span", "f", field + (secret ? " 🔒" : "")));
      c.title = secret ? T.secret : "env"; return c;
    }
    if (nodeId === "sys" || nodeId === "conversation") {
      const c = h("span", "chip plain"); c.appendChild(h("span", "", nodeId)); c.appendChild(h("span", "f", field)); return c;
    }
    if (nodeId === "context") { return h("span", "chip plain", T.context); }
    const n = byId[nodeId];
    if (!n) return h("code", "", field ? `${nodeId}.${field}` : nodeId);
    const a = h("a", "chip"); a.href = "#n/" + encodeURIComponent(nodeId); catStyle(a, n.category);
    a.appendChild(h("span", "", n.title));
    if (field) a.appendChild(h("span", "f", "› " + field));
    return a;
  }
  // Text that may contain {{#node.field#}} references and hardcoded email addresses.
  function rich(parent, text) {
    const re = /\{\{#([^#}]+)#\}\}|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g;
    let last = 0, m;
    text = String(text);
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1]) { const [id, ...rest] = m[1].split("."); parent.appendChild(chip(id, rest.join("."))); }
      else if (/@example\./i.test(m[2])) parent.appendChild(document.createTextNode(m[2]));
      else { const w = h("span", "warn", "⚠ " + m[2]); w.title = T.fixed; parent.appendChild(w); }
      last = re.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }

  // ---------- safe Markdown subset (DOM only) ----------
  function inline(parent, text, refs) {
    const re = /\[\[([^\]]+)\]\]|(`+)([\s\S]*?)\2|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        const inner = m[1].trim();
        const parts = inner.includes("›") ? inner.split("›").map((s) => s.trim()) : [inner.split(".")[0], inner.split(".").slice(1).join(".")];
        const id = byId[parts[0]] ? parts[0] : (g.nodes.find((n) => n.title === parts[0]) || {}).id;
        if (id) { parent.appendChild(chip(id, parts[1] || "")); if (refs) refs.add(id); }
        else parent.appendChild(h("code", "", inner));
      } else if (m[2]) parent.appendChild(h("code", "", m[3]));
      else if (m[4] !== undefined) { const s = h("strong"); inline(s, m[4], refs); parent.appendChild(s); }
      else if (/^https?:\/\//i.test(m[6])) { const a = h("a", "", m[5]); a.href = m[6]; a.rel = "noopener noreferrer"; a.target = "_blank"; parent.appendChild(a); }
      else { parent.appendChild(document.createTextNode(m[5] + " (")); parent.appendChild(h("code", "", m[6])); parent.appendChild(document.createTextNode(")")); }
      last = re.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  }
  function renderMarkdown(container, src, refs, hooks) {
    const lines = src.replace(/\r\n?/g, "\n").split("\n");
    let i = 0;
    const isSep = (s) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(s);
    const cells = (s) => s.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
    function code() {
      const head = lines[i].trim().match(/^(`{3,})\s*(\w*)/), fence = head[1], lang = head[2].toLowerCase();
      const ind = lines[i].match(/^\s*/)[0].length, buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence)) { buf.push(lines[i].slice(Math.min(ind, lines[i].match(/^\s*/)[0].length))); i++; }
      i++;
      if (lang === "flow" || lang === "mermaid") {  // author-drawn diagram
        const fig = flowDiagram(buf.join("\n"));
        fig.classList.add("flow");
        if (refs) for (const m of buf.join("\n").matchAll(/[\w\-]+/g)) if (byId[m[0]]) refs.add(m[0]);
        return fig;
      }
      const pre = h("pre"), c = h("code"); rich(c, buf.join("\n")); pre.appendChild(c); return pre;
    }
    function quote() {
      const bq = h("blockquote"), buf = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { buf.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      renderMarkdown(bq, buf.join("\n"), refs); return bq;
    }
    function list(start, ordered) {
      const el = h(ordered ? "ol" : "ul"), base = lines[start].match(/^\s*/)[0].length;
      let li = null; i = start;
      while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) { i++; if (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i]) && lines[i].match(/^\s*/)[0].length >= base) continue; break; }
        const ind = line.match(/^\s*/)[0].length, m = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
        if (m && ind === base) { li = h("li"); inline(li, m[2], refs); el.appendChild(li); i++; }
        else if (m && ind > base && li) li.appendChild(list(i, /\d+\./.test(m[1])));
        else if (ind > base && li && /^\s*```/.test(line)) li.appendChild(code());
        else if (ind > base && li && /^\s*>/.test(line)) li.appendChild(quote());
        else if (ind > base && li) { li.appendChild(document.createTextNode(" ")); inline(li, line.trim(), refs); i++; }
        else break;
      }
      return el;
    }
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let m;
      if (/^\s*\[\[diagram\]\]\s*$/i.test(line)) { const ph = h("div"); ph.dataset.diagram = "1"; container.appendChild(ph); i++; continue; }
      if (/^\s*```/.test(line)) { container.appendChild(code()); continue; }
      if ((m = line.match(/^(#{2,4})\s+(.*)$/))) { const hd = h("h" + m[1].length); inline(hd, m[2], refs); container.appendChild(hd); i++; continue; }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { container.appendChild(h("hr")); i++; continue; }
      if (/^\s*>/.test(line)) { container.appendChild(quote()); continue; }
      if (line.includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
        const t = h("table"), th = h("thead"), tb = h("tbody"), tr = h("tr");
        for (const c of cells(line)) { const x = h("th"); inline(x, c, refs); tr.appendChild(x); }
        th.appendChild(tr); t.appendChild(th); i += 2;
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
          const r = h("tr"); for (const c of cells(lines[i])) { const x = h("td"); inline(x, c, refs); r.appendChild(x); }
          tb.appendChild(r); i++;
        }
        t.appendChild(tb); container.appendChild(t); continue;
      }
      if ((m = line.match(/^\s*([-*]|\d+\.)\s+/))) { container.appendChild(list(i, /\d+\./.test(m[1]))); continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(```|#{2,4}\s|>|[-*]\s|\d+\.\s|\[\[diagram\]\])/.test(lines[i])) { buf.push(lines[i].trim()); i++; }
      const p = h("p"); inline(p, buf.join(" "), refs); container.appendChild(p);
    }
  }

  // ---------- pages from the explanation ----------
  const pages = [];
  (function splitPages() {
    const lines = (md || "").replace(/\r\n?/g, "\n").split("\n");
    let cur = null, fence = null;
    for (const line of lines) {
      const f = line.trim().match(/^(`{3,})/);
      if (f) fence = fence ? (line.trim().startsWith(fence) ? null : fence) : f[1];
      const m = !fence && line.match(/^#\s+(.*)$/);
      if (m) { cur = { title: m[1].trim(), body: [] }; pages.push(cur); }
      else { if (!cur) { cur = { title: T.overview, body: [] }; pages.push(cur); } cur.body.push(line); }
    }
    for (const p of pages) p.body = p.body.join("\n").trim();
    if (!pages.length) pages.push({ title: T.overview, body: (g.description ? g.description + "\n\n" : "") + T.no_explanation });
    // Which nodes each page mentions (for sidebars, backlinks and mini diagrams)
    for (const p of pages) { p.refs = new Set(); renderMarkdown(h("div"), p.body, p.refs); }
  })();

  // ---------- layout + diagram ----------
  // Wrap text into lines by display width (full-width characters count as 2).
  function wrap(text, width, maxLines) {
    const lines = [];
    let cur = "", w = 0;
    for (const ch of String(text)) {
      const cw = /[ᄀ-￿]/.test(ch) ? 2 : 1;
      if (w + cw > width && cur) { lines.push(cur); cur = ""; w = 0; }
      cur += ch; w += cw;
    }
    if (cur) lines.push(cur);
    if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = clip(lines[maxLines - 1], width - 1) + (lines[maxLines - 1].endsWith("…") ? "" : "…"); }
    return lines;
  }
  // Text lines and height of a box: a title (≤2 lines), detail lines (≤4), and a small type line.
  function boxOf(n) {
    const title = wrap(n.title, 34, 2);
    const detail = [];
    for (const d of n.detail || []) if (d && d !== n.title) detail.push(...wrap(d, 40, 3));
    detail.length = Math.min(detail.length, 4);
    const height = 14 + title.length * 18 + (detail.length ? 4 + detail.length * 15 : 0) + (n.sub ? 16 : 0) + 6;
    return { title, detail, height: Math.max(48, height) };
  }
  function layout(ids, allEdges, heights) {
    const set = new Set(ids);
    const edges = allEdges.filter((e) => set.has(e.from) && set.has(e.to));
    const inc = {};
    for (const e of edges) (inc[e.to] = inc[e.to] || []).push(e.from);
    const depth = {};
    const dep = (id, stack) => {
      if (id in depth) return depth[id];
      if (stack.has(id)) return 0;
      stack.add(id);
      const ps = inc[id] || [];
      depth[id] = ps.length ? 1 + Math.max(...ps.map((p) => dep(p, stack))) : 0;
      stack.delete(id);
      return depth[id];
    };
    ids.forEach((id) => dep(id, new Set()));
    const levels = {};
    for (const id of ids) (levels[depth[id]] = levels[depth[id]] || []).push(id);
    const widest = Math.min(MAXROW, Math.max(1, ...Object.values(levels).map((l) => l.length)));
    const width = MARGIN * 2 + (widest - 1) * COL + W + LANE;
    const pos = {}, rank = {};
    let y = MARGIN;
    for (const d of Object.keys(levels).map(Number).sort((a, b) => a - b)) {
      let level = levels[d];
      if (d > 0) {
        const fb = Object.keys(rank).length;
        const key = (id) => { const r = (inc[id] || []).filter((p) => p in rank).map((p) => rank[p]); return r.length ? r.reduce((a, b) => a + b, 0) / r.length : fb; };
        level = level.map((id, k) => [id, key(id), k]).sort((a, b) => a[1] - b[1] || a[2] - b[2]).map((x) => x[0]);
      }
      level.forEach((id) => { rank[id] = Object.keys(rank).length; });
      for (let s = 0; s < level.length; s += MAXROW) {
        const row = level.slice(s, s + MAXROW), rw = (row.length - 1) * COL + W, left = (width - LANE - rw) / 2;
        const rowH = Math.max(...row.map((id) => heights[id]));
        row.forEach((id, k) => { pos[id] = { x: left + k * COL, y: y + (rowH - heights[id]) / 2, h: heights[id], level: d }; });
        y += rowH + GAP;
      }
    }
    return { pos, edges, width, height: y - GAP + MARGIN };
  }
  // Add the nodes that connect the given ones (on some path between two of them), so a page's
  // diagram is a connected story rather than isolated boxes. Skipped if it would add too many.
  function withPaths(ids) {
    const set = new Set(ids), out = {}, inc = {};
    for (const e of g.edges) { (out[e.from] = out[e.from] || []).push(e.to); (inc[e.to] = inc[e.to] || []).push(e.from); }
    const reach = (starts, adj) => {
      const seen = new Set(), stack = [...starts];
      while (stack.length) for (const x of adj[stack.pop()] || []) if (!seen.has(x)) { seen.add(x); stack.push(x); }
      return seen;
    };
    const between = [...reach(ids, out)].filter((x) => !set.has(x) && reach([x], out).size && [...reach([x], out)].some((y) => set.has(y)));
    return between.length <= 12 ? [...ids, ...between] : ids;
  }
  function isConnected(ids) {  // one component, ignoring edge direction
    const set = new Set(ids), adj = {};
    for (const e of g.edges) if (set.has(e.from) && set.has(e.to)) { (adj[e.from] = adj[e.from] || []).push(e.to); (adj[e.to] = adj[e.to] || []).push(e.from); }
    const seen = new Set([ids[0]]), stack = [ids[0]];
    while (stack.length) for (const x of adj[stack.pop()] || []) if (!seen.has(x)) { seen.add(x); stack.push(x); }
    return seen.size === set.size;
  }
  // Diagram of real DSL nodes (auto diagrams, neighborhoods, flow map): title, what it does, type.
  function diagram(ids, opts) {
    ids = ids.slice().sort((a, b) => order[a] - order[b]);
    const nodes = ids.map((id) => ({ id, title: byId[id].title, detail: byId[id].brief || [], sub: byId[id].type,
      category: byId[id].category, href: "#n/" + encodeURIComponent(id), dashed: !!byId[id].parent }));
    return drawGraph(nodes, g.edges, opts);
  }
  // Diagram written by Claude in a ```flow block (Mermaid flowchart subset):
  //   id[Title<br>what it does] --> other{Decision} -->|yes| third(Label):::llm
  // The first <br>-separated part is the box title, the rest are detail lines. An id equal to a DSL
  // node id links to that node page, takes its color, and shows the real node's name as the type line.
  function flowDiagram(src) {
    const nodes = new Map(), edges = [];
    const nodeRe = /^([\w\-]+)\s*(?:\[([^\]]*)\]|\(([^)]*)\)|\{([^}]*)\})?\s*(?::::(\w+))?$/;
    const add = (tok) => {
      const m = tok.trim().match(nodeRe);
      if (!m) return null;
      const id = m[1], label = m[2] ?? m[3] ?? m[4], real = byId[id];
      const cur = nodes.get(id) || { id, title: real ? real.title : id, detail: real ? real.brief || [] : [],
        sub: real ? real.type : "", category: real ? real.category : "other", href: real ? "#n/" + encodeURIComponent(id) : null };
      if (label !== undefined && label.trim() !== "") {
        const parts = label.replace(/^"(.*)"$/, "$1").split(/<br\s*\/?>|\\n/i).map((s) => s.trim()).filter(Boolean);
        cur.title = parts[0]; cur.detail = parts.slice(1);
        if (real) cur.sub = clip(real.title, 40);
      }
      if (m[4] !== undefined && !real) cur.category = "condition";
      if (m[5]) cur.category = m[5];
      nodes.set(id, cur);
      return id;
    };
    for (let line of src.split("\n")) {
      line = line.replace(/%%.*$/, "").trim();
      if (!line || /^(flowchart|graph)\b/i.test(line)) continue;
      const parts = line.split(/\s*(?:-->|-\.->|==>)\s*(?:\|([^|]*)\|\s*)?/);
      let prev = add(parts[0]);
      for (let k = 1; k + 1 < parts.length; k += 2) {
        const next = add(parts[k + 1]);
        if (prev && next) edges.push({ from: prev, to: next, label: parts[k] ? parts[k].trim() : null });
        prev = next;
      }
    }
    return drawGraph([...nodes.values()], edges, {});
  }
  function drawGraph(nodes, allEdges, opts) {
    opts = opts || {};
    const ids = nodes.map((n) => n.id), info = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const boxes = Object.fromEntries(nodes.map((n) => [n.id, boxOf(n)]));
    const L = layout(ids, allEdges, Object.fromEntries(ids.map((id) => [id, boxes[id].height])));
    const fig = h("figure", "diagram");
    const svg = sv("svg", { width: L.width, height: L.height, viewBox: `0 0 ${L.width} ${L.height}`, role: "img" });
    fig.appendChild(svg);
    const mk = sv("marker", { id: "arw" + Math.random().toString(36).slice(2), viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, sv("defs", {}, svg));
    sv("path", { d: "M0,0 L10,5 L0,10 z", fill: "var(--line)" }, mk);
    const eL = sv("g", {}, svg), lL = sv("g", {}, svg), nL = sv("g", {}, svg);
    let detour = 0;
    const pending = [];
    for (const e of L.edges) {
      const a = L.pos[e.from], b = L.pos[e.to];
      let d, lx, ly;
      if (b.level - a.level !== 1) {
        const off = 36 + 18 * (detour++ % 6), x1 = a.x + W, y1 = a.y + a.h / 2, x2 = b.x + W, y2 = b.y + b.h / 2, side = Math.max(x1, x2) + off;
        d = `M${x1},${y1} C${side},${y1} ${side},${y2} ${x2},${y2}`; lx = side - off / 4; ly = (y1 + y2) / 2;
      } else {
        const x1 = a.x + W / 2, y1 = a.y + a.h, x2 = b.x + W / 2, y2 = b.y, dy = Math.max(24, (y2 - y1) / 2);
        d = `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`; lx = (x1 + x2) / 2; ly = (y1 + y2) / 2;
      }
      const hl = opts.here && (e.from === opts.here || e.to === opts.here);
      sv("path", { class: "edge" + (hl ? " hl" : ""), d, "marker-end": `url(#${mk.id})` }, eL);
      if (e.label) {
        const lg = sv("g", { class: "elabel" + (hl ? " hl" : "") }, lL);
        const t = sv("text", { x: lx, y: ly + 3, "text-anchor": "middle" }, lg);
        t.textContent = clip(e.label === "ELSE" ? T.else : e.label, 44);
        sv("title", {}, lg).textContent = e.label;
        pending.push([lg, t]);
      }
    }
    if (opts.here) svg.classList.add("focus");
    for (const id of ids) {
      const n = info[id], p = L.pos[id], box = boxes[id];
      const grp = sv("g", { class: "node" + (id === opts.here ? " here" : ""), transform: `translate(${p.x},${p.y})` }, nL);
      if (opts.dim && opts.dim.has(id)) grp.setAttribute("opacity", "0.55");
      sv("rect", { width: W, height: box.height, rx: 10, fill: `var(--${n.category}-bg)`, stroke: `var(--${n.category}-bd)`, "stroke-dasharray": n.dashed ? "5 3" : "none" }, grp);
      let y = 22;
      for (const line of box.title) { sv("text", { x: 12, y, class: "title" }, grp).textContent = line; y += 18; }
      if (box.detail.length) y += 2;
      for (const line of box.detail) { sv("text", { x: 12, y, class: "detail" }, grp).textContent = line; y += 15; }
      if (n.sub) sv("text", { x: 12, y: box.height - 9, class: "sub" }, grp).textContent = clip(n.sub, 40);
      sv("title", {}, grp).textContent = [n.title, ...(n.detail || [])].join("\n");
      if (n.href) {
        grp.setAttribute("tabindex", 0); grp.setAttribute("role", "link");
        const go = () => { location.hash = n.href; };
        grp.addEventListener("click", go);
        grp.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") go(); });
      } else grp.style.cursor = "default";
    }
    if (opts.caption) fig.appendChild(h("figcaption", "", opts.caption));
    fig._sizeLabels = () => {
      for (const [lg, t] of pending.splice(0)) {
        const bb = t.getBBox();
        lg.insertBefore(sv("rect", { x: bb.x - 4, y: bb.y - 2, width: bb.width + 8, height: bb.height + 4, rx: 4 }), t);
      }
    };
    return fig;
  }
  function legend() {
    const names = { start: "Start / trigger", end: "Output", llm: "AI", tool: "Tool / code / API", condition: "Branch", loop: "Loop", template: "Data / variables", human: "Human input", other: "Other" };
    const used = new Set(g.nodes.map((n) => n.category));
    const box = h("div", "legend");
    for (const [k, label] of Object.entries(names)) {
      if (!used.has(k)) continue;
      const s = h("span"), d = h("span", "dot"); catStyle(d, k); s.appendChild(d); s.appendChild(document.createTextNode(label)); box.appendChild(s);
    }
    return box;
  }

  // ---------- sidebar ----------
  const side = document.getElementById("side");
  function buildSide() {
    side.replaceChildren(h("div", "app", g.name || "Dify workflow"), h("div", "mode", `${g.mode} · ${g.nodes.length} nodes`));
    pages.forEach((p, i) => { const a = h("a", "", p.title); a.href = "#p/" + i; side.appendChild(a); });
    const map = h("a", "", T.map); map.href = "#map"; side.appendChild(map);
    side.appendChild(h("h3", "", T.nodes));
    for (const n of g.nodes) {
      const a = h("a", n.parent ? "child" : ""); a.href = "#n/" + encodeURIComponent(n.id);
      const d = h("span", "dot"); catStyle(d, n.category); a.appendChild(d); a.appendChild(h("span", "", n.title));
      side.appendChild(a);
    }
  }
  function markActive() {
    for (const a of side.querySelectorAll("a")) a.classList.toggle("active", a.getAttribute("href") === location.hash);
  }

  // ---------- views ----------
  const content = document.getElementById("content"), toc = document.getElementById("toc");
  function finish(title) {
    document.title = `${title} · ${g.name}`;
    toc.replaceChildren();
    const hs = content.querySelectorAll("h2, h3");
    if (hs.length) {
      toc.appendChild(h("h4", "", T.on_this_page));
      hs.forEach((x, k) => { x.id = "s" + k; const a = h("a", "", x.textContent); a.href = "javascript:void 0";
        if (x.tagName === "H3") a.style.paddingLeft = "22px";
        a.addEventListener("click", () => x.scrollIntoView({ behavior: "smooth", block: "start" })); toc.appendChild(a); });
    }
    for (const f of content.querySelectorAll("figure.diagram")) f._sizeLabels && f._sizeLabels();
    markActive();
    window.scrollTo(0, 0);
  }
  function pager(prev, next) {
    const box = h("div", "pager");
    const mk = (x, arrow) => { if (!x) return h("span"); const a = h("a", "", arrow === "←" ? `← ${x[1]}` : `${x[1]} →`); a.href = x[0]; return a; };
    box.appendChild(mk(prev, "←")); box.appendChild(mk(next, "→")); return box;
  }
  function showPage(i) {
    const p = pages[i];
    content.replaceChildren(h("h1", "page", p.title));
    if (i === 0 && g.description) content.appendChild(h("p", "lead", g.description));
    const body = h("div"); renderMarkdown(body, p.body, null);
    const ids = [...p.refs].filter((id) => byId[id]);
    const ph = body.querySelector("[data-diagram]");
    // Concept pages get a diagram only where the author asked for one: a ```flow block (already
    // rendered) or a [[diagram]] line. [[diagram]] is drawn only if its nodes form one connected
    // graph; disconnected boxes explain nothing.
    if (ph) {
      const shown = withPaths(ids);
      if (ids.length >= 2 && isConnected(shown)) ph.replaceWith(diagram(shown, { dim: new Set(shown.filter((x) => !p.refs.has(x))) }));
      else ph.remove();
    }
    content.appendChild(body);
    content.appendChild(pager(i > 0 ? ["#p/" + (i - 1), pages[i - 1].title] : null,
      i < pages.length - 1 ? ["#p/" + (i + 1), pages[i + 1].title] : ["#map", T.map]));
    finish(p.title);
  }
  function showMap() {
    content.replaceChildren(h("h1", "page", T.map), h("p", "lead", T.click_hint));
    content.appendChild(diagram(g.nodes.map((n) => n.id), {}));
    content.appendChild(legend());
    for (const t of g.notes || []) content.appendChild(h("blockquote", "", t));
    finish(T.map);
  }
  function table(headers, rows) {
    const t = h("table"), th = h("thead"), tr = h("tr");
    headers.forEach((x) => tr.appendChild(h("th", "", x))); th.appendChild(tr); t.appendChild(th);
    const tb = h("tbody");
    for (const r of rows) { const row = h("tr"); r.forEach((cell, k) => { const td = h("td", k === 0 ? "name" : ""); if (typeof cell === "function") cell(td); else td.textContent = cell; row.appendChild(td); }); tb.appendChild(row); }
    t.appendChild(tb); return t;
  }
  function showNode(id) {
    const n = byId[id];
    if (!n) return showPage(0);
    const crumb = h("div", "crumb", T.nodes + " › " + n.type);
    const title = h("h1", "page"); const b = h("span", "badge", n.type); catStyle(b, n.category); title.appendChild(b); title.appendChild(document.createTextNode(n.title));
    content.replaceChildren(crumb, title);
    if (n.parent && byId[n.parent]) { const p = h("p", "lead"); p.appendChild(document.createTextNode("in ")); p.appendChild(chip(n.parent, "")); content.appendChild(p); }
    const mentioned = pages.map((p, i) => [p, i]).filter(([p]) => p.refs.has(id));
    if (mentioned.length) {
      const p = h("p", "lead"); p.appendChild(document.createTextNode(T.mentioned_in + ": "));
      mentioned.forEach(([pg, i], k) => { if (k) p.appendChild(document.createTextNode(" · ")); const a = h("a", "", pg.title); a.href = "#p/" + i; p.appendChild(a); });
      content.appendChild(p);
    }
    const prev = g.edges.filter((e) => e.to === id).map((e) => e.from);
    const next = g.edges.filter((e) => e.from === id);
    const near = [...new Set([...prev, id, ...next.map((e) => e.to)])];
    content.appendChild(h("h2", "", T.neighborhood));
    content.appendChild(diagram(near, { here: id }));

    const sec = (key) => n.fields.filter((f) => f.section === key);
    for (const [key, label] of [["inputs", T.inputs], ["settings", T.settings], ["outputs", T.outputs]]) {
      const rows = sec(key);
      if (!rows.length) continue;
      content.appendChild(h("h2", "", label));
      content.appendChild(table([T.field, T.value], rows.map((r) => [r.name, (td) => {
        if (!r.value.includes("\n")) return rich(td, r.value);
        const pre = h("pre"), c = h("code"); rich(c, r.value); pre.appendChild(c); td.appendChild(pre);  // multi-line bodies
      }])));
    }
    const branches = next.filter((e) => e.label);
    if (branches.length) {
      content.appendChild(h("h2", "", T.branches));
      content.appendChild(table([T.condition, T.goes_to], branches.map((e) => [e.label === "ELSE" ? T.else : e.label, (td) => td.appendChild(chip(e.to, ""))])));
    }
    const used = Object.entries(n.used_by || {});
    if (used.length) {
      content.appendChild(h("h2", "", T.used_by));
      content.appendChild(table([T.field, T.used_in], used.map(([f, ids]) => [f, (td) => ids.forEach((x) => td.appendChild(chip(x, "")))])));
    }
    if ((n.content || []).length) {
      content.appendChild(h("h2", "", T.content));
      for (const blk of n.content) {
        content.appendChild(h("div", "block-label", blk.label));
        const pre = h("pre"), c = h("code"); rich(c, blk.text); pre.appendChild(c); content.appendChild(pre);
      }
    }
    const k = order[id];
    content.appendChild(pager(k > 0 ? ["#n/" + encodeURIComponent(g.nodes[k - 1].id), g.nodes[k - 1].title] : null,
      k < g.nodes.length - 1 ? ["#n/" + encodeURIComponent(g.nodes[k + 1].id), g.nodes[k + 1].title] : null));
    finish(n.title);
  }
  function route() {
    const hsh = decodeURIComponent(location.hash.slice(1));
    if (hsh === "map") return showMap();
    if (hsh.startsWith("n/")) return showNode(hsh.slice(2));
    const m = hsh.match(/^p\/(\d+)$/);
    showPage(m && pages[+m[1]] ? +m[1] : 0);
  }
  buildSide();
  window.addEventListener("hashchange", route);
  if (!location.hash) history.replaceState(null, "", "#p/0");
  route();
})();
</script>
</body>
</html>
"""


def inert_json(value) -> str:
    """JSON that cannot close or confuse the surrounding <script> block."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("graph", help="JSON from analyze_dsl.py --graph-json ('-' for stdin)")
    ap.add_argument("-o", "--output", required=True, help="HTML file to write")
    ap.add_argument("--explanation", help="Markdown explanation; each '# Heading' becomes a page")
    ap.add_argument("--lang", default="ja", choices=sorted(UI_TEXT), help="language of the page chrome (default: ja)")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.graph == "-" else Path(args.graph).read_text(encoding="utf-8")
    graph = json.loads(raw)
    graph["ui"] = UI_TEXT[args.lang]
    explanation = Path(args.explanation).read_text(encoding="utf-8") if args.explanation else ""
    title = (graph.get("name") or "Dify workflow").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = TEMPLATE.replace("__TITLE__", title).replace("__LANG__", args.lang)
    # Substitute the untrusted data last, in one pass, so inserted text is never re-scanned for placeholders.
    payload = {"__EXPLANATION__": inert_json(explanation), "__DATA__": inert_json(graph)}
    html = re.sub(r"__EXPLANATION__|__DATA__", lambda m: payload[m.group(0)], html)
    Path(args.output).write_text(html, encoding="utf-8")
    pages = sum(1 for line in explanation.splitlines() if re.match(r"#\s", line))
    print(f"wrote {args.output} ({len(graph['nodes'])} node pages, {pages} explanation page(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
