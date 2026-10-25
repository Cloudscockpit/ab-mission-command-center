"""Static pieces of the mission dashboard: CSS, JS and the HTML document skeleton.

Pure data, no logic. render_dashboard.py fills the skeleton and pins the exact
CSS and JS text in a Content-Security-Policy meta tag, so these strings are
emitted byte for byte.
"""

from string import Template

CSS = r"""
/* Hallmark · shape: app screen · genre: modern-minimal · theme: custom · nav: none, one page of read-only panels · signature: the agent workload donut, every segment labelled and listed · states: full, not recorded, scripting off
 * axes: dark canvas, hairline panels, system sans with mono figures, one container recipe · copy: verbatim, agent and registry text is shown as written · contrast: pass · v2.0.0 */
/* Hallmark · pre-emit critique: P3 H4 E4 S3 R4 V3 · weakest: S, a dashboard of panels could belong to any tool; the donut and gate verdict wording come only from the mission's own report and registry */
/* Hallmark · waive 72 · closed details lists keep hidden text laid out below their card · Touched files and Assignment outcomes sit in closed native details lists whose hidden text the box check measures as overflowing the card */
:root {
  color-scheme: dark;
  --bg: #0a0c10;
  --surface: #11141a;
  --surface-2: #171b23;
  --track: #222834;
  --rule: rgba(255, 255, 255, 0.08);
  --edge: #6c7486;
  --ink: #e6e9ef;
  --ink-2: #b4bbc9;
  --muted: #8f98aa;
  --focus: #9db8f5;
  --ok: #5ccf9b;
  --fail: #ef7d86;
  --ok-ink: #8fe0b6;
  --ok-bg: #12261d;
  --warn-ink: #e5c45c;
  --warn-bg: #2a2411;
  --on-data: #0a0c10;
  --agent-main: #c3c7d1;
  --agent-green: #5ccf9b;
  --agent-red: #ef7d86;
  --agent-yellow: #e5c45c;
  --agent-blue: #6fa6ee;
  --font-ui: Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "Geist Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --text-xs: 0.75rem;
  --text-sm: 0.8125rem;
  --text-base: 0.9375rem;
  --text-lg: 1.125rem;
  --text-xl: 1.5rem;
  --text-fig: 2rem;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;
  --radius: 8px;
  --container: 85rem;
  --gutter: 16px;
  --section-gap: 40px;
}
@media (min-width: 40rem) {
  :root { --gutter: 24px; --section-gap: 48px; }
}
@media (min-width: 60rem) {
  :root { --gutter: 32px; --section-gap: 56px; }
}

*, *::before, *::after { box-sizing: border-box; }
html { overflow-x: clip; -webkit-text-size-adjust: 100%; text-size-adjust: 100%; scrollbar-color: var(--track) var(--bg); }
body {
  margin: 0;
  overflow-x: clip;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-ui);
  font-size: var(--text-base);
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  caret-color: var(--focus);
}
::selection { background: var(--track); color: var(--ink); }
h1, h2, h3, p, dl, dd, ul, ol, figure { margin: 0; }
ul, ol { padding: 0; list-style: none; }
h1, h2, h3 { font-weight: 600; color: var(--ink); overflow-wrap: break-word; min-width: 0; text-wrap: balance; }
p { text-wrap: pretty; }
code, .num, .mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }

.wrap {
  width: 100%;
  max-width: var(--container);
  margin-inline: auto;
  padding-inline: var(--gutter);
  padding-block: var(--space-6) var(--space-8);
}
.section { margin-top: var(--section-gap); }
.section > h2 { font-size: var(--text-lg); line-height: 1.3; margin-bottom: var(--space-4); }
.note { color: var(--muted); font-size: var(--text-sm); }
.na { color: var(--muted); font-size: var(--text-base); font-weight: 400; }
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
.sr-copy { position: fixed; top: 0; left: 0; width: 1px; height: 1px; opacity: 0; pointer-events: none; }

.card {
  background: var(--surface);
  color: var(--ink);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  padding: var(--space-4);
  min-width: 0;
}

.head h1 { font-size: var(--text-xl); line-height: 1.25; }
.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
  gap: var(--space-4) var(--space-5);
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--rule);
}
.meta > div { min-width: 0; }
.meta dt, .kpi dt, .agent dt { color: var(--muted); font-size: var(--text-sm); }
.meta dd { margin-top: var(--space-1); overflow-wrap: break-word; }
.badge {
  display: inline-block;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--rule);
  border-radius: 999px;
  font-size: var(--text-sm);
  font-weight: 600;
  line-height: 1.4;
}
.badge-ok { background: var(--ok-bg); color: var(--ok-ink); }
.badge-warn { background: var(--warn-bg); color: var(--warn-ink); }
.badge-na { color: var(--muted); font-weight: 400; }

.summaries {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--space-3);
}
@media (min-width: 50rem) {
  .summaries {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.summary-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.summary-card h3 {
  color: var(--ink-2);
  font-size: var(--text-sm);
  font-weight: 600;
}
.summary-text {
  color: var(--ink);
  font-size: var(--text-base);
  line-height: 1.6;
}

.kpis { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
.kpi dd.fig {
  margin-top: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-fig);
  font-weight: 500;
  line-height: 1.15;
  overflow-wrap: break-word;
  min-width: 0;
}
.kpi dd.fig.na { font-family: var(--font-ui); font-size: var(--text-lg); }
.kpi .sub { margin-top: var(--space-2); color: var(--ink-2); font-size: var(--text-sm); overflow-wrap: break-word; }
.suites { margin-top: var(--space-3); }

.workload { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); }
.donut-card { display: grid; gap: var(--space-4); align-content: start; justify-items: center; }
.donut { display: block; width: 100%; max-width: 15rem; min-width: 12.5rem; height: auto; }
.seg { fill: none; stroke-width: 18; }
.seg-main { stroke: var(--agent-main); }
.seg-green { stroke: var(--agent-green); }
.seg-red { stroke: var(--agent-red); }
.seg-yellow { stroke: var(--agent-yellow); }
.seg-blue { stroke: var(--agent-blue); }
.ring-empty { fill: none; stroke: var(--track); stroke-width: 18; }
.seg-count { fill: var(--on-data); font-family: var(--font-mono); font-size: 8px; font-weight: 600; text-anchor: middle; dominant-baseline: central; }
.donut-total { fill: var(--ink); font-family: var(--font-mono); font-size: 22px; font-weight: 500; text-anchor: middle; dominant-baseline: central; }
.donut-cap { fill: var(--ink-2); font-family: var(--font-ui); font-size: 7.5px; text-anchor: middle; dominant-baseline: central; }
.legend { display: grid; gap: var(--space-2); width: 100%; }
.legend li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: var(--space-2); align-items: center; font-size: var(--text-sm); }
.sw { display: block; width: 12px; height: 12px; border-radius: 2px; }
.sw-main { background: var(--agent-main); }
.sw-green { background: var(--agent-green); }
.sw-red { background: var(--agent-red); }
.sw-yellow { background: var(--agent-yellow); }
.sw-blue { background: var(--agent-blue); }

.agents { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr)); gap: var(--space-3); align-content: start; }
.agent { display: grid; gap: var(--space-3); align-content: start; }
.agent h3 { font-size: var(--text-base); line-height: 1.3; }
.agent .role { color: var(--ink-2); font-size: var(--text-sm); }
.agent-top { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--space-3); align-items: center; }
.agent dl { display: grid; gap: var(--space-2); }
.agent dl > div { display: grid; grid-template-columns: minmax(0, 6rem) minmax(0, 1fr); gap: var(--space-2); }
.agent dd { overflow-wrap: break-word; min-width: 0; font-size: var(--text-sm); }
.agent .na { font-size: var(--text-sm); }
.outcomes > summary { font-size: var(--text-sm); }
.outcomes ol { display: grid; gap: var(--space-3); padding-top: var(--space-2); }
.outcomes li { font-size: var(--text-sm); color: var(--ink-2); overflow-wrap: break-word; }
.outcomes strong { color: var(--ink); font-weight: 600; }
.outcomes .err { color: var(--fail); margin-top: var(--space-1); }

.stages { display: grid; gap: 0; padding: 0; }
.stage { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); padding: var(--space-4); border-top: 1px solid var(--rule); }
.stage:first-child { border-top-color: var(--surface); }
.stage h3 { font-size: var(--text-base); line-height: 1.3; }
.mlabel { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-1) var(--space-3); margin-bottom: var(--space-2); font-size: var(--text-sm); color: var(--ink-2); }
.mlabel .num { color: var(--ink); }
.bar { display: block; width: 100%; height: 0.5rem; border-radius: 2px; }
.bar .t { fill: var(--track); }
.bar .p { fill: var(--ok); }
.bar .f { fill: var(--fail); }
.bar .k { stroke: var(--ink); stroke-width: 1; vector-effect: non-scaling-stroke; }
.gates { margin-top: var(--space-3); }

details > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 2.75rem;
  cursor: pointer;
  list-style: none;
  color: var(--ink);
}
details > summary::-webkit-details-marker { display: none; }
details > summary::after {
  content: "";
  flex: none;
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--muted);
  border-bottom: 2px solid var(--muted);
  transform: rotate(45deg);
  transition: transform 120ms ease-out;
}
details[open] > summary::after { transform: rotate(-135deg); }
.sum-main { flex: 1; min-width: 0; overflow-wrap: break-word; }
.sum-sub { color: var(--muted); font-size: var(--text-sm); }
.accordion { display: grid; gap: var(--space-2); }
.group { padding: var(--space-1) var(--space-4); }
.group > summary { padding-block: var(--space-1); }
.files { margin-top: var(--space-2); border-top: 1px solid var(--rule); }
.files li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-1) var(--space-3);
  align-items: center;
  padding-block: var(--space-2);
  border-top: 1px solid var(--rule);
}
.files li:first-child { border-top: 0; }
.fpath { font-size: var(--text-sm); word-break: break-all; }
.fstat { display: block; margin-top: var(--space-1); color: var(--muted); font-size: var(--text-xs); }
.gate-list { display: grid; gap: var(--space-3); padding-bottom: var(--space-3); }
.gate-list li { font-size: var(--text-sm); color: var(--ink-2); overflow-wrap: break-word; }
.gate-list strong { color: var(--ink); font-weight: 600; }

.copy {
  min-height: 2.75rem;
  min-width: 2.75rem;
  padding: 0 var(--space-3);
  background: none;
  border: 1px solid var(--edge);
  border-radius: 6px;
  color: var(--ink);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 120ms ease-out, border-color 120ms ease-out;
}
.copy[hidden] { display: none; }
.copy:active { transform: translateY(1px); }
.copy:disabled { opacity: 0.55; cursor: not-allowed; }
@media (hover: hover) {
  .copy:hover { background: var(--surface-2); border-color: var(--ink-2); }
  details > summary:hover { color: var(--ink-2); }
}
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

.foot { margin-top: var(--section-gap); padding-top: var(--space-4); border-top: 1px solid var(--rule); color: var(--muted); font-size: var(--text-sm); }

@media (min-width: 40rem) {
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stage { grid-template-columns: minmax(6rem, 10rem) minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-5); align-items: start; }
}
@media (min-width: 60rem) {
  .kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .workload { grid-template-columns: minmax(0, 20rem) minmax(0, 1fr); gap: var(--space-4); }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
}
"""

JS = r"""
(function () {
  var live = document.getElementById("copy-status");
  var buttons = document.querySelectorAll("button[data-path]");
  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.className = "sr-copy";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    document.body.removeChild(area);
    return ok;
  }
  function finish(button, label, ok, text) {
    button.textContent = ok ? "Copied" : "Copy failed";
    if (live) { live.textContent = ok ? "Copied " + text : "Could not copy " + text; }
    window.setTimeout(function () { button.textContent = label; }, 1600);
  }
  Array.prototype.forEach.call(buttons, function (button) {
    var label = button.textContent;
    button.hidden = false;
    button.addEventListener("click", function () {
      var text = button.dataset.path;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () { finish(button, label, true, text); },
          function () { finish(button, label, legacyCopy(text), text); }
        );
      } else {
        finish(button, label, legacyCopy(text), text);
      }
    });
  });
})();
"""

DOCUMENT = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="$csp">
<meta name="color-scheme" content="dark">
<meta name="description" content="$description">
<title>$title</title>
<style>$css</style>
</head>
<body>
<div class="wrap">
$body
</div>
<p id="copy-status" class="sr-only" role="status"></p>
<script>$script</script>
</body>
</html>
"""
)
