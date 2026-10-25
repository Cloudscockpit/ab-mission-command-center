#!/usr/bin/env python3
"""Build the mission dashboard: mission-metrics.json and mission-report.html.

Python 3.9+ standard library only. The page is one self-contained file: inline
CSS, inline SVG and a few lines of JavaScript for the copy-path buttons. It
makes no network request and pins its inline style and script with a
Content-Security-Policy hash.

Collect the numbers no other file stores (run at the end of the mission):

    python render_dashboard.py metrics --out mission-metrics.json \\
        --mission add-health-endpoint \\
        --started-at 2026-10-26T09:00:00Z --ended-at 2026-10-26T09:14:32Z \\
        --git-base main \\
        --test "unit,python -m unittest discover -s tests,142,0,3"

Render the dashboard next to the other mission documents:

    python render_dashboard.py render --report mission-report.jsonld \\
        --registry .actionboard/registry.json --metrics mission-metrics.json \\
        --mission add-health-endpoint --operator-level L4 --out mission-report.html \\
        [--generated-at 2026-10-26T09:20:00Z]

A figure with no source prints "Not recorded", never zero.
"""

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dashboard_template as T  # noqa: E402

NOT_RECORDED = "Not recorded"
FILE_PREFIX = "urn:voltron:file:"
AGENTS = [
    ("main", "Black Agent", "Lead"),
    ("green", "Green Agent", "Recon"),
    ("red", "Red Agent", "Core builds"),
    ("yellow", "Yellow Agent", "QA and security"),
    ("blue", "Blue Agent", "Packaging"),
]
STAGES = [
    ("orchestrator", "Orchestrator"),
    ("data", "Data"),
    ("analysis", "Analysis"),
    ("action", "Action"),
    ("defense", "Defense/Audit"),
]
STATUS_WORDS = {"Completed": "Completed", "Failed": "Failed", "Active": "In progress", "Potential": "Planned"}
STATUS_ORDER = ["Completed", "Failed", "In progress", "Planned"]
MODE_LABELS = {"guided": "Guided", "actionlist": "Actionlist", "autonomous": "Autonomous"}
FILE_STATUS = {"add": "Added", "edit": "Edited", "del": "Deleted"}
GIT_STATUS = {"A": "add", "C": "add", "M": "edit", "T": "edit", "R": "edit", "D": "del"}


def fail(message):
    sys.stderr.write("render_dashboard: %s\n" % " ".join(str(message).split()))
    sys.exit(2)


# ----------------------------------------------------------------- text helpers

def e(value):
    return html.escape(str(value), quote=True)


def text_of(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("description", "text", "value", "name"):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
        return ""
    if isinstance(value, list):
        return " ".join(part for part in (text_of(v) for v in value) if part)
    return ""


def parse_ts(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def iso_z(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(moment):
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def fmt_duration(seconds):
    seconds = int(round(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return "%dd %dh %dm" % (days, hours, minutes)
    if hours:
        return "%dh %dm %ds" % (hours, minutes, secs)
    if minutes:
        return "%dm %02ds" % (minutes, secs)
    return "%ds" % secs


def num(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def fnum(value):
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def check_out(out, inputs):
    if os.path.isdir(out):
        fail("--out %s is a directory" % out)
    target = os.path.normcase(os.path.realpath(out))
    for flag, path in inputs:
        if not path or not os.path.exists(path):
            continue
        same = os.path.normcase(os.path.realpath(path)) == target
        if not same and os.path.exists(out):
            same = os.path.samefile(out, path)
        if same:
            fail("--out %s would overwrite %s" % (out, flag))


def atomic_write(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    tmp = None
    try:
        os.makedirs(parent, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".part")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        fail("cannot write --out %s: %s" % (path, exc.strerror or exc))
    except BaseException:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


# --------------------------------------------------------------------- metrics

def parse_test(spec):
    parts = spec.split(",")
    if len(parts) < 5:
        fail('invalid --test %r: expected "name,command,passed,failed,skipped"' % spec)
    name = parts[0].strip()
    command = ",".join(parts[1:-3]).strip()
    counts = {}
    for key, raw in zip(("passed", "failed", "skipped"), parts[-3:]):
        raw = raw.strip()
        if raw == "":
            continue
        if not re.fullmatch(r"[0-9]+", raw):
            fail("invalid --test %r: %s must be a whole number or empty" % (spec, key))
        counts[key] = int(raw)
    if not name:
        fail("invalid --test %r: name is empty" % spec)
    row = {"name": name}
    if command:
        row["command"] = command
    row.update(counts)
    return row


def check_git_ref(ref):
    if not ref or ref.startswith("-") or re.search(r"[\s\x00-\x1f\x7f]", ref):
        fail("--git-base %r is not a safe git ref" % ref)


def git_files(ref):
    check_git_ref(ref)
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-status", "-z", ref, "--"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        fail("could not run git: %s" % exc)
    if proc.returncode != 0:
        fail("git diff failed for --git-base %r: %s" % (ref, proc.stderr.decode("utf-8", "replace").strip()))
    tokens = proc.stdout.decode("utf-8", "replace").split("\0")
    files, seen, i = [], set(), 0
    while i < len(tokens) and tokens[i]:
        code = tokens[i][0]
        width = 2 if code in "RC" else 1
        paths = tokens[i + 1:i + 1 + width]
        i += 1 + width
        if len(paths) < width or code not in GIT_STATUS:
            continue
        path = paths[-1]
        if path not in seen:
            seen.add(path)
            files.append({"path": path, "status": GIT_STATUS[code]})
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        if top.returncode != 0:
            fail("git rev-parse failed: %s" % top.stderr.decode("utf-8", "replace").strip())
        root = top.stdout.decode("utf-8", "replace").strip()
        other = subprocess.run(
            ["git", "-C", root, "ls-files", "--others", "--exclude-standard", "--full-name", "-z", "--"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        fail("could not run git: %s" % exc)
    if other.returncode != 0:
        fail("git ls-files failed: %s" % other.stderr.decode("utf-8", "replace").strip())
    for path in other.stdout.decode("utf-8", "replace").split("\0"):
        if path and path not in seen:
            seen.add(path)
            files.append({"path": path, "status": "add"})
    return files


def cmd_metrics(args):
    if not args.mission.strip():
        fail("--mission is empty")
    data = {"mission": args.mission}
    for flag, key in (("started_at", "started_at"), ("ended_at", "ended_at")):
        raw = getattr(args, flag)
        if raw is None:
            continue
        moment = parse_ts(raw)
        if moment is None:
            fail("--%s %r is not an ISO 8601 time" % (flag.replace("_", "-"), raw))
        data[key] = iso_z(moment)
    check_out(args.out, [])
    if args.test:
        data["tests"] = [parse_test(spec) for spec in args.test]
    if args.git_base is not None:
        data["files"] = git_files(args.git_base)
    atomic_write(args.out, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return 0


# ----------------------------------------------------------------------- input

MAX_INPUT = 16 * 1024 * 1024


def read_json(path):
    with open(path, "rb") as fh:
        raw = fh.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("file is larger than 16 MB")
    try:
        return json.loads(raw.decode("utf-8"))
    except RecursionError:
        raise ValueError("JSON is nested too deeply")


def load_report(path):
    try:
        data = read_json(path)
    except OSError as exc:
        fail("cannot read --report %s: %s" % (path, exc.strerror or exc))
    except ValueError as exc:
        fail("--report %s is not valid JSON: %s" % (path, exc))
    graph = data.get("@graph") if isinstance(data, dict) else data
    if not isinstance(graph, list):
        fail("--report %s has no @graph array" % path)
    return [node for node in graph if isinstance(node, dict)]


def has_type(node, name):
    kind = node.get("@type")
    return kind == name or (isinstance(kind, list) and name in kind)


def tail(value, sep=":"):
    if isinstance(value, dict):
        value = value.get("@id")
    return value.rsplit(sep, 1)[-1] if isinstance(value, str) else None


def pick_outcome(result):
    terms = result if isinstance(result, list) else ([] if result is None else [result])
    named = {}
    for term in terms:
        if isinstance(term, dict):
            named.setdefault(str(term.get("name", "")).lower(), text_of(term))
        elif isinstance(term, str):
            named.setdefault("", term)
    if named.get("outcome"):
        return named["outcome"]
    for key, value in named.items():
        if key != "acceptance" and value:
            return value
    return None


def report_model(graph):
    project = next((n for n in graph if has_type(n, "Project")), {})
    assignments = []
    for node in graph:
        node_id = node.get("@id")
        match = re.search(r":assignment:(\d+)$", node_id) if isinstance(node_id, str) else None
        if not match or not has_type(node, "Action"):
            continue
        status = tail(node.get("actionStatus"), "/")
        if status:
            status = status[:-len("ActionStatus")] if status.endswith("ActionStatus") else status
            status = STATUS_WORDS.get(status, status)
        objects = node.get("object")
        if isinstance(objects, dict):
            objects = [objects]
        files, listed = [], set()
        for obj in objects if isinstance(objects, list) else []:
            ident = obj.get("@id") if isinstance(obj, dict) else None
            if isinstance(ident, str) and ident.startswith(FILE_PREFIX) and ident[len(FILE_PREFIX):]:
                path = ident[len(FILE_PREFIX):]
                if path not in listed:
                    listed.add(path)
                    files.append(path)
        assignments.append({
            "n": int(match.group(1)),
            "name": text_of(node.get("name")) or "Untitled assignment",
            "agent": tail(node.get("agent")),
            "status": status or None,
            "outcome": pick_outcome(node.get("result")) or None,
            "error": text_of(node.get("error")) or None,
            "files": files,
        })
    assignments.sort(key=lambda a: a["n"])
    report = next((n for n in graph if has_type(n, "Report")), {})
    return {
        "title": text_of(project.get("name")) or None,
        "ident": project.get("identifier") if isinstance(project.get("identifier"), str) else None,
        "description": text_of(project.get("description")) or None,
        "outcome": text_of(report.get("abstract")) or None,
        "assignments": assignments,
    }


def load_optional(path, label):
    if not path or not os.path.isfile(path):
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        sys.stderr.write("render_dashboard: ignoring unreadable %s %s: %s\n" % (label, path, exc))
        return None
    return data


def mission_runs(registry, slug):
    runs = []
    actions = registry.get("actions") if isinstance(registry, dict) else None
    for action in actions if isinstance(actions, list) else []:
        listed = action.get("runs") if isinstance(action, dict) else None
        for run in listed if isinstance(listed, list) else []:
            if isinstance(run, dict) and run.get("mission") == slug:
                runs.append(run)
    return runs


def run_maturity(registry_path, slug, level):
    """Return (summary or None, reason or None)."""
    script = os.path.normpath(os.path.join(
        HERE, "..", "..", "actionboard-devops-mission", "scripts", "maturity.py"))
    if slug.startswith("-"):
        return None, "mission slug starts with a dash"
    if not os.path.isfile(script):
        return None, "maturity.py not found next to this skill"
    cmd = [sys.executable, script, "summary", "--registry", registry_path, "--mission", slug, "--json"]
    if level:
        cmd += ["--operator-level", level]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "maturity.py timed out after 60 seconds"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "could not run maturity.py: %s" % exc
    if proc.returncode != 0:
        lines = [ln.strip() for ln in proc.stderr.decode("utf-8", "replace").splitlines() if ln.strip()]
        return None, "maturity.py exited %d: %s" % (proc.returncode, (lines[-1] if lines else "no message")[:160])
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except (ValueError, RecursionError):
        return None, "maturity.py printed unreadable output"
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        return None, "maturity.py printed an unexpected summary"
    return data, None


def distinct_actions(maturity):
    last = {}
    for row in maturity["actions"] if maturity else []:
        if isinstance(row, dict):
            last[row.get("action_id", row.get("name"))] = row
    return list(last.values())


def valid_metrics(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    start, end = parse_ts(raw.get("started_at")), parse_ts(raw.get("ended_at"))
    if start:
        out["start"] = start
    if end:
        out["end"] = end
    tests = raw.get("tests")
    if isinstance(tests, list):
        out["tests"] = [t for t in tests if isinstance(t, dict) and isinstance(t.get("name"), str)]
    files = raw.get("files")
    if isinstance(files, list):
        out["files"] = [f for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)
                        and isinstance(f.get("status"), str) and f["status"] in FILE_STATUS]
    return out


# ------------------------------------------------------------------- fragments

def na(text=NOT_RECORDED):
    return '<span class="na">%s</span>' % e(text)


def kpi(label, fig, sub="", extra="", missing=False):
    fig_html = '<dd class="fig na">%s</dd>' % e(NOT_RECORDED) if missing else '<dd class="fig">%s</dd>' % fig
    sub_html = '<p class="sub">%s</p>' % sub if sub else ""
    return '<div class="card kpi"><dl><dt>%s</dt>%s</dl>%s%s</div>' % (e(label), fig_html, sub_html, extra)


def kpi_duration(m):
    if "start" in m and "end" in m and m["end"] >= m["start"]:
        seconds = (m["end"] - m["start"]).total_seconds()
        return kpi("Duration", e(fmt_duration(seconds)), "Started %s" % e(fmt_ts(m["start"])))
    return kpi("Duration", "", missing=True)


def kpi_files(m):
    if "files" not in m:
        return kpi("Files changed", "", missing=True)
    counts = dict.fromkeys(("add", "edit", "del"), 0)
    for item in m["files"]:
        counts[item["status"]] += 1
    return kpi("Files changed", "+%d ~%d -%d" % (counts["add"], counts["edit"], counts["del"]),
               "Added, edited, deleted")


def kpi_tests(m):
    tests = [t for t in m.get("tests", []) if num(t.get("passed"))]
    if not tests:
        return kpi("Tests passed", "", missing=True)
    passed = sum(t["passed"] for t in tests)
    bits = []
    for key in ("failed", "skipped"):
        rows = [t[key] for t in m["tests"] if num(t.get(key))]
        if rows:
            bits.append("%d %s" % (sum(rows), key))
    sub = ", ".join(bits) or "%d suite%s" % (len(tests), "" if len(tests) == 1 else "s")
    items = []
    for t in m["tests"]:
        figures = ", ".join("%s %d" % (k, t[k]) for k in ("passed", "failed", "skipped") if num(t.get(k)))
        command = t.get("command")
        items.append("<li><strong>%s</strong> %s%s</li>" % (
            e(t["name"]), e(figures) if figures else na(),
            (' <code>%s</code>' % e(command)) if isinstance(command, str) and command else ""))
    extra = ('<details class="suites"><summary><span class="sum-main">Test suites</span></summary>'
             '<ul class="gate-list">%s</ul></details>' % "".join(items))
    return kpi("Tests passed", e(str(passed)), e(sub), extra)


def pick_autonomy(rows):
    pool = [r for r in rows if num(r.get("clean_runs")) and num(r.get("clean_runs_required"))
            and r["clean_runs_required"] > 0]
    if not pool:
        return None
    auto = [r for r in pool if r.get("mode") == "autonomous"]
    if auto:
        return auto[0]
    return max(pool, key=lambda r: (r["clean_runs"] / float(r["clean_runs_required"]), r["clean_runs"]))


def kpi_autonomy(rows):
    row = pick_autonomy(rows)
    if row is None:
        return kpi("Autonomy clean runs", "", missing=True)
    name = str(row.get("name") or row.get("action_id") or "")
    mode = row.get("mode")
    if mode == "autonomous":
        sub = "Autonomous unlocked for %s" % name
    else:
        sub = "%s mode for %s" % (MODE_LABELS.get(mode, str(mode) if mode else "Mode not recorded"), name)
    return kpi("Autonomy clean runs", "%d/%d" % (row["clean_runs"], row["clean_runs_required"]), e(sub.strip()))


def donut(counts):
    total = sum(n for _, _, n in counts)
    parts = ['<svg class="donut" viewBox="0 0 120 120" role="img" aria-label="%s">']
    if total == 0:
        label = "Assignments per Agent: %s" % NOT_RECORDED
        parts.append('<circle class="ring-empty" cx="60" cy="60" r="45"/>'
                     '<text class="donut-cap" x="60" y="60">%s</text></svg>' % e(NOT_RECORDED))
        return parts[0] % e(label) + "".join(parts[1:])
    radius = 45.0
    circ = 2 * math.pi * radius
    gap = 2.4
    segs = [(k, name, n) for k, name, n in counts if n > 0]
    circles, labels, cum = [], [], 0.0
    for key, _, n in segs:
        frac = n / float(total)
        if len(segs) == 1:
            dash, start = circ, 0.0
        else:
            dash, start = max(frac * circ - gap, 0.5), cum * circ + gap / 2
        circles.append(
            '<circle class="seg seg-%s" cx="60" cy="60" r="45" transform="rotate(-90 60 60)" '
            'stroke-dasharray="%s %s" stroke-dashoffset="%s"/>' % (
                key, fnum(dash), fnum(circ - dash), fnum(-start) if start else "0"))
        angle = (cum + frac / 2) * 2 * math.pi - math.pi / 2
        labels.append('<text class="seg-count" x="%s" y="%s">%d</text>' % (
            fnum(60 + radius * math.cos(angle)), fnum(60 + radius * math.sin(angle)), n))
        cum += frac
    summary = "Assignments per Agent, %d in total: %s" % (
        total, ", ".join("%s %d" % (name, n) for _, name, n in segs))
    return (parts[0] % e(summary) + "".join(circles) + "".join(labels)
            + '<text class="donut-total" x="60" y="55">%d</text>'
              '<text class="donut-cap" x="60" y="72">assignments</text></svg>' % total)


def legend(counts):
    total = sum(n for _, _, n in counts)
    items = []
    for key, name, n in counts:
        if n > 0:
            items.append('<li><span class="sw sw-%s" aria-hidden="true"></span><span>%s</span>'
                         '<span class="num">%d (%d%%)</span></li>' % (
                             key, e(name), n, int(round(100.0 * n / total))))
    return '<ul class="legend">%s</ul>' % "".join(items)


def outcome_summary(rows):
    tally = {}
    for row in rows:
        if row["status"]:
            tally[row["status"]] = tally.get(row["status"], 0) + 1
    if not tally:
        return NOT_RECORDED
    ordered = [s for s in STATUS_ORDER if s in tally] + sorted(s for s in tally if s not in STATUS_ORDER)
    return ", ".join("%d %s" % (tally[s], s.lower()) for s in ordered)


def agent_card(key, name, role, rows, total):
    files = set()
    for row in rows:
        files.update(row["files"])
    if rows:
        share = "%d (%d%%)" % (len(rows), int(round(100.0 * len(rows) / total)))
        file_text = e(str(len(files))) if files else na("None listed")
        outcome = e(outcome_summary(rows)) if any(r["status"] for r in rows) else na()
        assign_html = '<span class="num">%s</span>' % e(share)
        file_html = '<span class="num">%s</span>' % file_text if files else file_text
        details_items = []
        for row in rows:
            body = e(row["outcome"]) if row["outcome"] else na()
            err = '<p class="err">Error: %s</p>' % e(row["error"]) if row["error"] else ""
            status = " (%s)" % e(row["status"]) if row["status"] else ""
            details_items.append("<li><strong>Assignment %d: %s</strong>%s<p>%s</p>%s</li>" % (
                row["n"], e(row["name"]), status, body, err))
        details = ('<details class="outcomes"><summary><span class="sum-main">Assignment outcomes</span></summary>'
                   "<ol>%s</ol></details>" % "".join(details_items))
    else:
        assign_html, file_html, outcome, details = e("None dispatched"), na(), na(), ""
    return (
        '<article class="card agent"><div class="agent-top"><span class="sw sw-%s" aria-hidden="true"></span>'
        '<div><h3>%s</h3><p class="role">%s</p></div></div>'
        '<dl><div><dt>Assignments</dt><dd>%s</dd></div><div><dt>Files</dt><dd>%s</dd></div>'
        '<div><dt>Outcome</dt><dd>%s</dd></div></dl>%s</article>' % (
            key, e(name), e(role), assign_html, file_html, outcome, details))


def bar(label, percent, background, threshold=None):
    tick = ""
    if threshold is not None:
        tick = '<line class="k" x1="%s" x2="%s" y1="0" y2="8"/>' % (fnum(threshold), fnum(threshold))
    return ('<svg class="bar" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="%s">'
            '<rect class="%s" x="0" y="0" width="100" height="8"/>'
            '<rect class="p" x="0" y="0" width="%s" height="8"/>%s</svg>' % (
                e(label), background, fnum(percent), tick))


def meter(title, value_text, svg):
    return ('<div><p class="mlabel"><span>%s</span><span class="num">%s</span></p>%s</div>' % (
        e(title), e(value_text), svg))


def stage_rows(runs, rows):
    threshold = None
    limits = {r.get("threshold") for r in rows if isinstance(r.get("threshold"), (int, float))}
    if len(limits) == 1:
        threshold = limits.pop() * 100.0
    out = []
    for key, label in STAGES:
        seen = [r["stages"][key] for r in runs if isinstance(r.get("stages"), dict)
                and isinstance(r["stages"].get(key), bool)]
        if seen:
            passed = sum(1 for v in seen if v)
            run_text = "%d of %d run%s passed" % (passed, len(seen), "" if len(seen) == 1 else "s")
            run_html = meter("This mission", run_text,
                             bar("%s, this mission: %s" % (label, run_text), 100.0 * passed / len(seen), "f"))
        else:
            run_html = meter("This mission", NOT_RECORDED, "")
        rates = [r["stage_rates"][key] for r in rows if isinstance(r.get("stage_rates"), dict)
                 and isinstance(r["stage_rates"].get(key), (int, float))]
        if rates:
            pct = 100.0 * sum(rates) / len(rates)
            win_text = "%d%% across %d action%s" % (int(round(pct)), len(rates), "" if len(rates) == 1 else "s")
            win_html = meter("Window pass rate", win_text,
                             bar("%s, window pass rate: %s" % (label, win_text), pct, "t", threshold))
        else:
            win_html = meter("Window pass rate", NOT_RECORDED, "")
        out.append('<li class="stage"><h3>%s</h3>%s%s</li>' % (e(label), run_html, win_html))
    return "".join(out), threshold


def gate_details(rows):
    if not rows:
        return ""
    items = []
    for row in rows:
        name = str(row.get("name") or row.get("action_id") or "Action")
        mode = row.get("mode")
        mode_text = MODE_LABELS.get(mode, str(mode)) if mode else NOT_RECORDED
        parts = [mode_text]
        if num(row.get("clean_runs")) and num(row.get("clean_runs_required")):
            parts.append("%d of %d clean runs" % (row["clean_runs"], row["clean_runs_required"]))
        reason = row.get("gate_reason") if isinstance(row.get("gate_reason"), str) else ""
        items.append("<li><strong>%s</strong> %s. %s</li>" % (e(name), e(", ".join(parts)), e(reason)))
    return ('<details class="card gates"><summary><span class="sum-main">Gate verdict by action</span>'
            '<span class="sum-sub">%d action%s</span></summary><ul class="gate-list">%s</ul></details>' % (
                len(rows), "" if len(rows) == 1 else "s", "".join(items)))


UNSAFE_PATH = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
MAX_LISTED = 1000


def visible_path(path):
    def show(match):
        char = match.group(0)
        named = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
        if char in named:
            return named[char]
        return "\\x%02x" % ord(char) if ord(char) < 256 else "\\u%04x" % ord(char)
    return UNSAFE_PATH.sub(show, path)


def copy_button(path):
    return ('<button type="button" class="copy" data-path="%s" aria-label="Copy path %s" hidden>Copy path</button>' % (
        e(path), e(path)))


def file_groups(assignments, metric_files):
    status = {f["path"]: f["status"] for f in metric_files or []}
    claimed, groups = set(), []
    for row in assignments:
        if row["files"]:
            claimed.update(row["files"])
            groups.append(("Assignment %d: %s" % (row["n"], row["name"]), row["files"]))
    extra, seen = [], set()
    for item in metric_files or []:
        if item["path"] not in claimed and item["path"] not in seen:
            seen.add(item["path"])
            extra.append(item["path"])
    if extra:
        groups.append(("Changed files not listed by an assignment", extra))
    out, budget, unlisted = [], MAX_LISTED, 0
    for title, paths in groups:
        shown = paths[:budget]
        budget -= len(shown)
        unlisted += len(paths) - len(shown)
        if not shown:
            continue
        rows = []
        for path in shown:
            tags = []
            if path in status:
                tags.append(FILE_STATUS[status[path]])
            unsafe = bool(UNSAFE_PATH.search(path))
            if unsafe:
                tags.append("No copy button: the path holds control or direction characters")
            tag = '<span class="fstat">%s</span>' % e(", ".join(tags)) if tags else ""
            rows.append('<li><div><code class="fpath">%s</code>%s</div>%s</li>' % (
                e(visible_path(path)), tag, "" if unsafe else copy_button(path)))
        out.append(
            '<details class="card group"><summary><span class="sum-main">%s</span>'
            '<span class="sum-sub">%d file%s</span></summary><ul class="files">%s</ul></details>' % (
                e(title), len(paths), "" if len(paths) == 1 else "s", "".join(rows)))
    if unlisted:
        out.append('<p class="note">%d more file%s not listed; see mission-report.jsonld</p>' % (
            unlisted, "" if unlisted == 1 else "s"))
    return "".join(out)


# ------------------------------------------------------------------------ page

def build_body(ctx):
    slug, model, m = ctx["slug"], ctx["model"], ctx["metrics"]
    runs, rows = ctx["runs"], ctx["rows"]
    assignments = model["assignments"]
    by_agent = dict((key, [a for a in assignments if a["agent"] == key]) for key, _, _ in AGENTS)
    counts = [(key, name, len(by_agent[key])) for key, name, _ in AGENTS]
    total = sum(n for _, _, n in counts)

    if not runs:
        badge = '<span class="badge badge-na">%s</span>' % e(NOT_RECORDED)
    elif any(r.get("first_attempt") is False for r in runs):
        badge = '<span class="badge badge-warn">Retried</span>'
    elif ctx["stage_failed"]:
        badge = '<span class="badge badge-warn">Stage failed</span>'
    else:
        badge = '<span class="badge badge-ok">Clean run</span>'
    level = ctx["level"]
    level_html = '<span class="mono">%s</span>' % e(level) if level else na()
    gen = ctx["generated"]

    head = (
        '<header class="head"><h1>%s</h1><dl class="meta">'
        '<div><dt>Mission ID</dt><dd class="mono">%s</dd></div>'
        '<div><dt>Status</dt><dd>%s</dd></div>'
        '<div><dt>Operator level</dt><dd>%s</dd></div>'
        '<div><dt>Generated</dt><dd class="mono"><time datetime="%s">%s</time></dd></div>'
        "</dl></header>" % (e(model["title"] or slug), e(slug), badge, level_html, e(iso_z(gen)), e(fmt_ts(gen))))

    kpis = (
        '<section class="section" aria-labelledby="h-kpi"><h2 id="h-kpi">Key figures</h2><div class="kpis">%s%s%s%s</div></section>'
        % (kpi_duration(m), kpi_files(m), kpi_tests(m), kpi_autonomy(rows)))

    if assignments:
        cards = "".join(agent_card(key, name, role, by_agent[key], max(total, 1)) for key, name, role in AGENTS)
        workload_body = (
            '<div class="card donut-card">%s%s</div><div class="agents">%s</div>' % (
                donut(counts), legend(counts) if total else "", cards))
    else:
        workload_body = '<div class="card donut-card">%s</div>' % na()
    workload = ('<section class="section" aria-labelledby="h-work"><h2 id="h-work">Agent workload</h2>'
                '<div class="workload">%s</div></section>' % workload_body)

    stage_html, threshold = stage_rows(runs, rows)
    thr_note = ('<p class="note">The vertical mark on each window bar is the pass-rate threshold, %d%%.</p>'
                % int(round(threshold))) if threshold is not None else ""
    stages = ('<section class="section" aria-labelledby="h-stage"><h2 id="h-stage">Stage maturity</h2>'
              '<ul class="card stages">%s</ul>%s%s</section>' % (stage_html, thr_note, gate_details(rows)))

    groups = file_groups(assignments, m.get("files"))
    files = ('<section class="section" aria-labelledby="h-files"><h2 id="h-files">Touched files</h2>%s</section>' % (
        '<div class="accordion">%s</div>' % groups if groups else '<p class="card">%s</p>' % na()))

    summary_parts = []
    if model.get("description"):
        summary_parts.append(
            '<article class="card summary-card">'
            '<h3>Mission objective</h3>'
            '<p class="summary-text">%s</p>'
            '</article>' % e(model["description"]))
    if model.get("outcome"):
        summary_parts.append(
            '<article class="card summary-card">'
            '<h3>Outcome &amp; results</h3>'
            '<p class="summary-text">%s</p>'
            '</article>' % e(model["outcome"]))
    if summary_parts:
        summary_section = (
            '<section class="section" aria-labelledby="h-summary">'
            '<h2 id="h-summary">Executive summary</h2>'
            '<div class="summaries">%s</div>'
            '</section>' % "".join(summary_parts))
    else:
        summary_section = ""

    foot = ('<footer class="foot">Sources: mission-report.jsonld, the registry runs for this mission, '
            'maturity.py and mission-metrics.json.</footer>')
    sections = [head, "<main>"]
    if summary_section:
        sections.append(summary_section)
    sections.extend([kpis, workload, stages, files, "</main>", foot])
    return "\n".join(sections)


def sha_source(text):
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def cmd_render(args):
    check_out(args.out, [("--report", args.report), ("--registry", args.registry), ("--metrics", args.metrics)])
    graph = load_report(args.report)
    model = report_model(graph)
    slug = args.mission
    registry = load_optional(args.registry, "--registry")
    metrics = valid_metrics(load_optional(args.metrics, "--metrics"))
    runs = mission_runs(registry, slug) if registry is not None else []
    maturity = None
    if registry is not None:
        maturity, why = run_maturity(args.registry, slug, args.operator_level)
        if why:
            sys.stderr.write("render_dashboard: WARNING maturity figures not available (%s); showing %s\n" % (
                " ".join(why.split()), NOT_RECORDED))
    rows = distinct_actions(maturity)
    stage_failed = any(isinstance(r.get("stages"), dict) and any(v is False for v in r["stages"].values())
                       for r in runs)
    stage_failed = stage_failed or any(isinstance(r, dict) and r.get("clean_run") is False
                                       for r in (maturity or {}).get("actions", []))

    level = args.operator_level
    if not level and maturity and num(maturity.get("operator_level")):
        level = "L%d" % maturity["operator_level"]

    if args.generated_at:
        generated = parse_ts(args.generated_at)
        if generated is None:
            fail("--generated-at %r is not an ISO 8601 time" % args.generated_at)
    else:
        generated = metrics.get("end") or datetime.now(timezone.utc)

    body = build_body({"slug": slug, "model": model, "metrics": metrics, "runs": runs, "rows": rows,
                       "level": level, "generated": generated, "stage_failed": stage_failed})
    csp = ("default-src 'none'; style-src %s; script-src %s; base-uri 'none'; form-action 'none'"
           % (sha_source(T.CSS), sha_source(T.JS)))
    description = "Mission report dashboard for %s: status, key figures, agent workload, stage maturity and touched files." % slug
    page = T.DOCUMENT.substitute(
        csp=csp, description=e(description), title=e("Mission report: %s" % (model["title"] or slug)),
        css=T.CSS, script=T.JS, body=body)
    atomic_write(args.out, page)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    met = sub.add_parser("metrics", help="write mission-metrics.json")
    met.add_argument("--out", required=True)
    met.add_argument("--mission", required=True)
    met.add_argument("--started-at", dest="started_at", help="ISO 8601 UTC time of the go approval")
    met.add_argument("--ended-at", dest="ended_at", help="ISO 8601 UTC time of the report")
    met.add_argument("--git-base", dest="git_base", help="ref to diff the working tree against")
    met.add_argument("--test", action="append", help='"name,command,passed,failed,skipped" (repeatable)')
    met.set_defaults(func=cmd_metrics)

    ren = sub.add_parser("render", help="write mission-report.html")
    ren.add_argument("--report", required=True, help="mission-report.jsonld")
    ren.add_argument("--registry", default=".actionboard/registry.json")
    ren.add_argument("--metrics", help="mission-metrics.json")
    ren.add_argument("--mission", required=True, help="mission slug")
    ren.add_argument("--operator-level", dest="operator_level", help="L1-L7 (else .actionboard/config.json)")
    ren.add_argument("--out", required=True)
    ren.add_argument("--generated-at", dest="generated_at", help="ISO 8601 time to print; default is the metrics end time, else now")
    ren.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
