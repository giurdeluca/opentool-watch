"""
Dashboard: one self-contained HTML page (no internet needed to open it) summarising every
paper in papers.sqlite, with filters, basic charts and links to verify each paper.

Written by pipeline.py after each run, or rebuilt from an existing database without
querying OpenAlex:

    python dashboard.py --config examples/ldct/config.yaml --data ./data
"""

import argparse
import html
import json
import os

COLUMNS = [
    "id", "title", "date", "venue", "type", "doi", "landing_url", "oa_pdf_url", "code_urls",
    "code_source", "queries", "cited_by", "first_seen", "screened", "screened_on",
    "dup_type", "dup_title", "dup_link", "dup_score",
]


def collect(db, review_rx):
    """Every paper as a dict, plus the run history. Flags are computed here, not stored."""
    rows = db.execute(
        "SELECT p.id, p.title, p.publication_date, p.venue, p.type, p.doi, p.landing_url,"
        " p.oa_pdf_url, p.code_urls, p.code_source, p.queries, p.cited_by, p.first_seen,"
        " p.screened, p.screened_on, d.type, d.title, COALESCE(d.doi, d.id), p.duplicate_score"
        " FROM papers p LEFT JOIN papers d ON d.id = p.duplicate_of"
        " ORDER BY p.publication_date DESC"
    ).fetchall()
    papers = []
    for r in rows:
        p = dict(zip(COLUMNS, r))
        hit = review_rx.search(p["title"] or "") if review_rx else None
        p["likely_review"] = hit.group(0).lower() if hit else ""
        p["code_urls"] = (p["code_urls"] or "").split()
        p["queries"] = (p["queries"] or "").split(",")
        papers.append(p)
    runs = db.execute("SELECT run_date, new_papers FROM runs ORDER BY run_date").fetchall()
    return papers, [{"date": d, "new": n} for d, n in runs]


def write_dashboard(db, out_dir, cfg, review_rx):
    papers, runs = collect(db, review_rx)
    data = {
        "title": cfg.get("title") or "opentool-watch",
        "queries": list(cfg.get("queries", {})),
        "last_run": runs[-1]["date"] if runs else None,
        "runs": runs,
        "papers": papers,
    }
    # "</" inside the JSON would end the <script> element early; "<\/" is the same JSON string.
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (TEMPLATE.replace("__TITLE__", html.escape(data["title"]))
                    .replace("__DATA__", blob))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dashboard.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path


def main():
    import yaml
    import pipeline  # imported here: pipeline imports this module too

    ap = argparse.ArgumentParser(description="Rebuild the dashboard from papers.sqlite")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data")
    args = ap.parse_args()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    db = pipeline.open_db(os.path.join(args.data, "papers.sqlite"))
    path = write_dashboard(db, os.path.join(args.data, "out"), cfg,
                           pipeline.review_regex(cfg.get("review_title_terms", [])))
    print(path)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series: #2a78d6; --context: #d6d5ce; --link: #1c5cab; --chip: #f0efec;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series: #3987e5; --context: #45443f; --link: #86b6ef; --chip: #2c2c2a;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a988f;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series: #3987e5; --context: #45443f; --link: #86b6ef; --chip: #2c2c2a;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1200px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 12px; }
.sub { color: var(--ink-2); margin: 0 0 20px; }
a { color: var(--link); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center;
  margin-bottom: 16px; }
.filters input[type=search], .filters select { font: inherit; color: var(--ink);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 8px; min-width: 0; }
.filters input[type=search] { flex: 1 1 220px; }
.filters label { display: inline-flex; gap: 6px; align-items: center; color: var(--ink-2); }
.filters button { font: inherit; background: none; border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 10px; color: var(--ink-2); cursor: pointer; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 16px; }
.tile .v { font-size: 26px; font-weight: 600; }
.tile .k { color: var(--ink-2); }
.tile .n { color: var(--muted); font-size: 12px; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr));
  gap: 12px; margin-bottom: 16px; }
.chart svg { display: block; overflow: visible; }
.chart text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.chart text.lbl { fill: var(--ink-2); }
.chart text.val { fill: var(--ink); }
.chart .hit { fill: transparent; cursor: default; }
.chart g.mark:hover rect.fill, .chart g.mark:focus rect.fill { opacity: .78; }
.chart g.mark:focus { outline: none; }
.chart g.mark:focus rect.hit { stroke: var(--ink-2); stroke-width: 1; }
.legend { display: flex; gap: 14px; color: var(--ink-2); font-size: 12px; margin: -4px 0 8px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 5px; vertical-align: -1px; }
details { margin-top: 8px; color: var(--ink-2); font-size: 12px; }
details table { border-collapse: collapse; margin-top: 6px; }
details td, details th { padding: 2px 10px 2px 0; text-align: left;
  font-variant-numeric: tabular-nums; }
#tip { position: fixed; pointer-events: none; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,.12); display: none; z-index: 10; max-width: 260px; }
#tip b { font-size: 13px; }
.tablewrap { overflow-x: auto; }
table.papers { width: 100%; border-collapse: collapse; }
table.papers th { text-align: left; font-weight: 600; color: var(--ink-2); font-size: 12px;
  border-bottom: 1px solid var(--axis); padding: 6px 8px; white-space: nowrap; }
table.papers th button { font: inherit; color: var(--link); background: none; border: 0;
  padding: 0; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
table.papers th button::after { content: attr(data-arrow); }
table.papers td { border-bottom: 1px solid var(--grid); padding: 8px; vertical-align: top; }
td.num { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
td.code { min-width: 180px; }
.meta { color: var(--muted); font-size: 12px; }
.links a, .code a { margin-right: 8px; white-space: nowrap; }
.code a { display: block; overflow-wrap: anywhere; white-space: normal; }
.chip { display: inline-block; background: var(--chip); color: var(--ink-2); border-radius: 4px;
  padding: 1px 6px; font-size: 12px; margin: 0 4px 4px 0; }
.count { color: var(--ink-2); margin: 0 0 8px; }
.more { margin-top: 12px; }
@media (max-width: 640px) {
  table.papers thead { display: none; }
  table.papers tr { display: block; border-bottom: 1px solid var(--axis); padding: 6px 0; }
  table.papers td { display: block; border: 0; padding: 3px 0; }
  td.num { text-align: left; }
  td[data-k]::before { content: attr(data-k) ": "; color: var(--muted); font-size: 12px; }
  table.papers td:empty { display: none; }
}
</style>
</head>
<body>
<main>
  <h1 id="title"></h1>
  <p class="sub" id="sub"></p>

  <div class="filters" role="search">
    <input type="search" id="q" placeholder="Search title, venue, code link" aria-label="Search">
    <select id="f-signal" aria-label="Code signal"></select>
    <select id="f-query" aria-label="Query"></select>
    <select id="f-type" aria-label="Type"></select>
    <label><input type="checkbox" id="f-new"> new in last run</label>
    <label><input type="checkbox" id="f-noreview"> hide likely reviews</label>
    <label><input type="checkbox" id="f-dup"> only possible duplicates</label>
    <label>Sort by <select id="sort" aria-label="Sort papers by">
      <option value="date:-1">newest first</option>
      <option value="date:1">oldest first</option>
      <option value="cited_by:-1">most cited</option>
      <option value="cited_by:1">least cited</option>
      <option value="first_seen:-1">recently found</option>
      <option value="title:1">title A–Z</option>
    </select></label>
    <button id="reset" type="button">Reset</button>
  </div>

  <p class="meta" style="margin:-8px 0 12px">Summary and charts follow all filters except
    the code-signal one (they show that split); the table follows all filters.</p>
  <section class="tiles" id="tiles" aria-label="Summary"></section>

  <section class="charts">
    <div class="card chart"><h2>Papers per publication year</h2>
      <div class="legend"><span><i style="background:var(--series)"></i>code signal</span>
        <span><i style="background:var(--context)"></i>no code signal</span></div>
      <div id="c-year"></div></div>
    <div class="card chart"><h2>Where the code signal was found</h2><div id="c-source"></div></div>
    <div class="card chart"><h2>Code signal by query</h2><div id="c-query"></div></div>
    <div class="card chart"><h2>Papers by type</h2><div id="c-type"></div></div>
  </section>

  <section class="card">
    <h2>Papers</h2>
    <p class="count" id="count"></p>
    <div class="tablewrap"><table class="papers">
      <thead><tr>
        <th><button data-sort="title">Paper</button></th>
        <th><button data-sort="date">Date</button></th>
        <th>Code</th><th>Flags</th><th>Verify</th>
        <th><button data-sort="cited_by">Cited by</button></th>
        <th><button data-sort="first_seen">First seen</button></th>
      </tr></thead>
      <tbody id="rows"></tbody>
    </table></div>
    <button class="more" id="more" type="button"></button>
  </section>
</main>
<div id="tip" role="tooltip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";
const PAGE = 200;
let shown = PAGE, sortKey = "date", sortDir = -1;

// Only http(s) links are rendered: the data comes from an external API.
function safeUrl(u) {
  try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; }
  catch (e) { return null; }
}
function el(tag, attrs, text) {
  const e = document.createElement(tag);
  for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}
function link(url, text) {
  const u = safeUrl(url);
  if (!u) return null;
  return el("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, text);
}
function s(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}
const fmt = (n) => n.toLocaleString("en");
const pct = (a, b) => b ? Math.round(100 * a / b) + "%" : "–";
const SIGNAL = { abstract: "link in abstract", fulltext: "mentioned in full text", pdf: "link in PDF" };

// ---------------------------------------------------------------- header & filters
$("title").textContent = D.title;
$("sub").textContent = `${fmt(D.papers.length)} papers tracked · ${D.runs.length} runs · last run ${D.last_run || "never"}`;
function options(sel, items) {
  for (const [v, t] of items) sel.append(el("option", { value: v }, t));
}
options($("f-signal"), [["code", "Any code signal"], ["all", "All papers"],
  ["abstract", SIGNAL.abstract], ["fulltext", SIGNAL.fulltext], ["pdf", SIGNAL.pdf],
  ["none", "No code signal"], ["pending", "Not screened yet"]]);
options($("f-query"), [["", "All queries"], ...D.queries.map((q) => [q, q])]);
const types = [...new Set(D.papers.map((p) => p.type || "unknown"))].sort();
options($("f-type"), [["", "All types"], ...types.map((t) => [t, t])]);

function filtered(ignoreSignal) {
  const q = $("q").value.trim().toLowerCase();
  const sig = $("f-signal").value, qn = $("f-query").value, ty = $("f-type").value;
  const isNew = $("f-new").checked, noRev = $("f-noreview").checked, dup = $("f-dup").checked;
  return D.papers.filter((p) => {
    if (!ignoreSignal) {
      if (sig === "code" && !p.code_source) return false;
      if (sig === "none" && (p.code_source || !p.screened)) return false;
      if (sig === "pending" && p.screened) return false;
      if (["abstract", "fulltext", "pdf"].includes(sig) && p.code_source !== sig) return false;
    }
    if (qn && !p.queries.includes(qn)) return false;
    if (ty && (p.type || "unknown") !== ty) return false;
    if (isNew && p.screened_on !== D.last_run) return false;
    if (noRev && p.likely_review) return false;
    if (dup && !p.dup_title) return false;
    if (q) {
      const hay = [p.title, p.venue, ...p.code_urls].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

// ---------------------------------------------------------------- tooltip
const tip = $("tip");
function showTip(evt, value, label) {
  tip.replaceChildren(el("b", {}, value), el("br"), document.createTextNode(label));
  tip.style.display = "block";
  let x, y;
  if (evt.clientX != null && evt.type !== "focus") { x = evt.clientX + 12; y = evt.clientY + 12; }
  else { const r = evt.currentTarget.getBoundingClientRect(); x = r.right + 6; y = r.top; }
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x, innerWidth - w - 8) + "px";
  tip.style.top = Math.min(y, innerHeight - h - 8) + "px";
}
function hideTip() { tip.style.display = "none"; }
function hover(g, value, label) {
  g.setAttribute("tabindex", "0");
  g.setAttribute("aria-label", `${label}: ${value}`);
  g.addEventListener("pointermove", (e) => showTip(e, value, label));
  g.addEventListener("focus", (e) => showTip(e, value, label));
  g.addEventListener("pointerleave", hideTip);
  g.addEventListener("blur", hideTip);
}
// Bar with only its data end rounded (4px), anchored square to the baseline.
function barPath(x, y, w, h, r, end) {
  r = Math.min(r, w / 2, h);
  if (h <= 0 || w <= 0) return "";
  if (end === "top") return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  if (end === "right") return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  return `M${x},${y}H${x + w}V${y + h}H${x}Z`;
}
function niceMax(v) {
  if (v <= 5) return 5;
  const p = Math.pow(10, Math.floor(Math.log10(v))), m = v / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
}
function tableView(rows, head) {
  const d = el("details"); d.append(el("summary", {}, "Show as table"));
  const t = el("table"), tr = el("tr");
  head.forEach((h) => tr.append(el("th", {}, h))); t.append(tr);
  rows.forEach((r) => { const x = el("tr"); r.forEach((c) => x.append(el("td", {}, c))); t.append(x); });
  d.append(t); return d;
}

// ---------------------------------------------------------------- charts
function yearChart(papers) {
  const by = {};
  for (const p of papers) {
    const y = (p.date || "").slice(0, 4) || "?";
    by[y] = by[y] || { code: 0, none: 0 };
    p.code_source ? by[y].code++ : by[y].none++;
  }
  const years = Object.keys(by).sort();
  const W = Math.max(260, $("c-year").clientWidth), H = 220, L = 40, B = 24, T = 18;
  const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Papers per publication year" });
  const max = niceMax(Math.max(1, ...years.map((y) => by[y].code + by[y].none)));
  const ph = H - B - T, sy = (v) => T + ph - (v / max) * ph;
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i, y = sy(v);
    svg.append(s("line", { x1: L, x2: W, y1: y, y2: y, stroke: i ? "var(--grid)" : "var(--axis)", "stroke-width": 1 }));
    svg.append(s("text", { x: L - 6, y: y + 4, "text-anchor": "end" }, fmt(v)));
  }
  const step = (W - L) / Math.max(1, years.length), bw = Math.min(36, step * 0.6);
  years.forEach((y, i) => {
    const c = by[y], x = L + i * step + (step - bw) / 2, g = s("g", { class: "mark" });
    const yc = sy(c.code), yt = sy(c.code + c.none);
    g.append(s("rect", { class: "hit", x: L + i * step, y: T, width: step, height: ph }));
    if (c.none) g.append(s("path", { class: "fill", d: barPath(x, yt, bw, Math.max(0, yc - yt - (c.code ? 2 : 0)), 4, "top"), fill: "var(--context)" }));
    if (c.code) g.append(s("path", { class: "fill", d: barPath(x, yc, bw, sy(0) - yc, 4, c.none ? "none" : "top"), fill: "var(--series)" }));
    if (years.length <= 12 || i % 2 === 0) svg.append(s("text", { x: x + bw / 2, y: H - 6, "text-anchor": "middle" }, y));
    hover(g, `${fmt(c.code)} of ${fmt(c.code + c.none)} with code signal (${pct(c.code, c.code + c.none)})`, y);
    svg.append(g);
  });
  const box = $("c-year"); box.replaceChildren(svg,
    tableView(years.map((y) => [y, fmt(by[y].code + by[y].none), fmt(by[y].code), pct(by[y].code, by[y].code + by[y].none)]),
      ["year", "papers", "code signal", "share"]));
}
function hbarChart(boxId, items, total, unit) {
  const box = $(boxId);
  if (!items.length) { box.replaceChildren(el("p", { class: "meta" }, "Nothing matches the filters.")); return; }
  const W = Math.max(260, box.clientWidth), rowH = 28, L = Math.min(170, W * 0.42), R = 56;
  const H = items.length * rowH + 4;
  const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": boxId });
  const max = Math.max(1, ...items.map((d) => d[1])), sx = (v) => (v / max) * (W - L - R);
  items.forEach(([label, v], i) => {
    const y = i * rowH + 4, g = s("g", { class: "mark" });
    g.append(s("rect", { class: "hit", x: 0, y, width: W, height: rowH - 2 }));
    const maxCh = Math.floor((L - 8) / 6);
    g.append(s("text", { class: "lbl", x: L - 8, y: y + 16, "text-anchor": "end" }, label.length > maxCh ? label.slice(0, maxCh - 1) + "…" : label));
    g.append(s("path", { class: "fill", d: barPath(L, y + 5, Math.max(2, sx(v)), 14, 4, "right"), fill: "var(--series)" }));
    g.append(s("text", { class: "val", x: L + Math.max(2, sx(v)) + 6, y: y + 16 }, fmt(v)));
    hover(g, `${fmt(v)} ${unit}${total ? ` (${pct(v, total)})` : ""}`, label);
    svg.append(g);
  });
  svg.append(s("line", { x1: L, x2: L, y1: 0, y2: H, stroke: "var(--axis)", "stroke-width": 1 }));
  box.replaceChildren(svg);
}
function countBy(papers, keyFn) {
  const m = new Map();
  for (const p of papers) for (const k of [].concat(keyFn(p))) if (k != null) m.set(k, (m.get(k) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

// ---------------------------------------------------------------- tiles
function tiles(all) {
  const code = all.filter((p) => p.code_source), screened = all.filter((p) => p.screened);
  const items = [
    ["Papers", fmt(all.length), `${fmt(all.length - screened.length)} not screened yet`],
    ["With code signal", fmt(code.length), `${pct(code.length, screened.length)} of screened`],
    ["Link in abstract/PDF", fmt(code.filter((p) => p.code_source !== "fulltext").length), "URL extracted"],
    ["New in last run", fmt(code.filter((p) => p.screened_on === D.last_run).length), "with code signal"],
    ["Likely reviews", fmt(code.filter((p) => p.likely_review).length), "with code signal"],
    ["Possible duplicates", fmt(code.filter((p) => p.dup_title).length), "with code signal"],
  ];
  $("tiles").replaceChildren(...items.map(([k, v, n]) => {
    const t = el("div", { class: "card tile" });
    t.append(el("div", { class: "k" }, k), el("div", { class: "v" }, v), el("div", { class: "n" }, n));
    return t;
  }));
}

// ---------------------------------------------------------------- table
function row(p) {
  const tr = el("tr");
  const td1 = el("td");
  const t = link(p.doi || p.landing_url || p.id, p.title || "(untitled)");
  td1.append(t || el("span", {}, p.title || "(untitled)"));
  td1.append(el("div", { class: "meta" }, [p.venue, p.type, p.queries.join(", ")].filter(Boolean).join(" · ")));
  const td2 = el("td", { "data-k": "date", class: "num" }, p.date || "");
  const td3 = el("td", { class: "code", "data-k": "code" });
  if (p.code_source) td3.append(el("span", { class: "chip" }, SIGNAL[p.code_source] || p.code_source));
  for (const u of p.code_urls) { const a = link(u, u.replace(/^https?:\/\/(www\.)?/, "")); if (a) td3.append(a); }
  const td4 = el("td", { "data-k": "flags" });
  if (p.likely_review) td4.append(el("span", { class: "chip" }, `likely review (“${p.likely_review}”)`));
  if (p.dup_title) {
    const d = el("div", { class: "meta" });
    d.append(document.createTextNode(`possible duplicate (${p.dup_score}) of ${p.dup_type}: `));
    d.append(link(p.dup_link, p.dup_title) || document.createTextNode(p.dup_title));
    td4.append(d);
  }
  const td5 = el("td", { class: "links", "data-k": "verify" });
  for (const [u, txt] of [[p.doi, "DOI"], [p.landing_url, "publisher"], [p.oa_pdf_url, "PDF"], [p.id, "OpenAlex"]]) {
    const a = u && link(u, txt); if (a) td5.append(a);
  }
  const td6 = el("td", { class: "num", "data-k": "cited by" }, p.cited_by == null ? "" : fmt(p.cited_by));
  const td7 = el("td", { class: "num", "data-k": "first seen" }, p.first_seen || "");
  tr.append(td1, td2, td3, td4, td5, td6, td7);
  return tr;
}
function compare(a, b, k, dir) {
  const x = a[k], y = b[k];
  const missX = x == null || x === "", missY = y == null || y === "";
  if (missX || missY) return missX - missY;  // missing values last, whatever the direction
  return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
}
function syncSort() {
  const v = `${sortKey}:${sortDir}`;
  if ([...$("sort").options].some((o) => o.value === v)) $("sort").value = v;
  document.querySelectorAll("th button[data-sort]").forEach((b) => {
    const on = b.dataset.sort === sortKey;
    b.dataset.arrow = on ? (sortDir < 0 ? " ↓" : " ↑") : "";
    b.closest("th").setAttribute("aria-sort", on ? (sortDir < 0 ? "descending" : "ascending") : "none");
  });
}
function table(sel) {
  const k = sortKey, dir = sortDir;
  syncSort();
  // Ties (e.g. equal citations) fall back to newest first.
  const rows = [...sel].sort((a, b) => compare(a, b, k, dir) || compare(a, b, "date", -1));
  $("count").textContent = `${fmt(rows.length)} papers match the filters` + (rows.length > shown ? `, showing the first ${fmt(shown)}` : "");
  $("rows").replaceChildren(...rows.slice(0, shown).map(row));
  $("more").style.display = rows.length > shown ? "" : "none";
  $("more").textContent = `Show ${fmt(Math.min(PAGE, rows.length - shown))} more`;
}

// ---------------------------------------------------------------- render
function render() {
  // Tiles and charts follow every filter except the code-signal one, because they show
  // the split between papers with and without a code signal; the table follows all filters.
  const scope = filtered(true), code = scope.filter((p) => p.code_source);
  tiles(scope);
  yearChart(scope);
  hbarChart("c-source", countBy(code, (p) => SIGNAL[p.code_source] || p.code_source), code.length, "papers");
  hbarChart("c-query", countBy(code, (p) => p.queries), code.length, "papers with code signal");
  hbarChart("c-type", countBy(scope, (p) => p.type || "unknown"), scope.length, "papers");
  table(filtered(false));
}
for (const id of ["q", "f-signal", "f-query", "f-type", "f-new", "f-noreview", "f-dup"])
  $(id).addEventListener("input", () => { shown = PAGE; render(); });
$("reset").addEventListener("click", () => {
  $("q").value = ""; $("f-signal").value = "code"; $("f-query").value = ""; $("f-type").value = "";
  for (const id of ["f-new", "f-noreview", "f-dup"]) $(id).checked = false;
  sortKey = "date"; sortDir = -1;
  shown = PAGE; render();
});
$("more").addEventListener("click", () => { shown += PAGE; table(filtered(false)); });
document.querySelectorAll("th button[data-sort]").forEach((b) => b.addEventListener("click", () => {
  const k = b.dataset.sort;
  sortDir = sortKey === k ? -sortDir : (k === "title" ? 1 : -1); sortKey = k;
  table(filtered(false));
}));
$("sort").addEventListener("input", () => {
  const [k, d] = $("sort").value.split(":");
  sortKey = k; sortDir = Number(d); table(filtered(false));
});
let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
