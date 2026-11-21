#!/usr/bin/env python3
"""Deterministic compiler from ActionBoard V5 Markdown mission docs to schema.org JSON-LD.

Eliminates hand-authoring 500-1,200 line JSON-LD graphs via LLM output tokens.
Standard library only; Python 3.9+.

Usage:
    python compile_jsonld.py brief  --md mission-brief.md  --out mission-brief.jsonld  [--slug <slug>] [--date YYYY-MM-DD]
    python compile_jsonld.py plan   --md mission-plan.md   --out mission-plan.jsonld   [--brief mission-brief.jsonld] [--slug <slug>]
    python compile_jsonld.py report --md mission-report.md --out mission-report.jsonld [--plan mission-plan.jsonld] [--registry .actionboard/registry.json] [--slug <slug>]
    python compile_jsonld.py validate <path-or-dir> [...]
"""

import argparse
import datetime
import json
import os
import re
import sys

SCHEMA_CTX = "https://schema.org"

AGENT_INFO = {
    "main": ("Black Agent", "Mission commander (Black Agent). Plans, delegates, gates, reports."),
    "black": ("Black Agent", "Mission commander (Black Agent). Plans, delegates, gates, reports."),
    "red": ("Red Agent", "Rapid execution specialist (Red Agent). Builds features and ships code."),
    "blue": ("Blue Agent", "Data, infrastructure, and integration specialist (Blue Agent)."),
    "green": ("Green Agent", "Recon and analysis specialist (Green Agent). Maps the codebase."),
    "yellow": ("Yellow Agent", "Quality and defense specialist (Yellow Agent). Tests and security reviews."),
}

VALID_ACTION_STATUSES = {
    "https://schema.org/PotentialActionStatus",
    "https://schema.org/ActiveActionStatus",
    "https://schema.org/CompletedActionStatus",
    "https://schema.org/FailedActionStatus",
}

VALID_LIONS = {"red", "blue", "green", "yellow", "main"}


def slugify(text, max_len=48):
    words = re.sub(r"[^a-z0-9\s-]", " ", (text or "").lower()).split()
    drop = {"a", "an", "the"}
    kept = [w for w in words if w not in drop] or words
    slug = re.sub(r"-+", "-", "-".join(kept)).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "mission"


def infer_date_from_path(path):
    parts = os.path.abspath(path).replace("\\", "/").split("/")
    for seg in reversed(parts):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", seg)
        if m:
            return m.group(1)
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def infer_slug_from_path(path):
    parent = os.path.basename(os.path.dirname(os.path.abspath(path)))
    m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", parent)
    if m:
        return slugify(m.group(1))
    return ""


def strip_md_inline(text):
    t = (text or "").strip()
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"__([^_]+)__", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_h1(md_text):
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    if not m:
        return ""
    raw = m.group(1).strip()
    cleaned = re.sub(r"^Mission\s+(?:Brief|Plan|Report)\s*[:\u2014-]\s*", "", raw, flags=re.I)
    return strip_md_inline(cleaned or raw)


def parse_sections(md_text):
    """Return ordered list of (heading_lower, heading_raw, body) for level-2 (##) headings."""
    sections = []
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", md_text, re.M))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        raw = m.group(1).strip()
        sections.append((raw.lower(), raw, md_text[start:end].strip()))
    return sections


def find_section(sections, *keywords):
    for low, _raw, body in sections:
        for kw in keywords:
            if kw in low:
                return body
    return ""


def parse_bullets(body):
    items = []
    for line in (body or "").splitlines():
        m = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$", line)
        if m:
            val = strip_md_inline(m.group(1))
            if val:
                items.append(val)
    return items


def parse_first_paragraph(body):
    lines = []
    for line in (body or "").splitlines():
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        if s.startswith("#") or s.startswith("|") or s.startswith("```"):
            if lines:
                break
            continue
        lines.append(s)
    return strip_md_inline(" ".join(lines))


def parse_markdown_table(body):
    """Return list of dicts keyed by normalized lowercase column header."""
    table_lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip().startswith("|")]
    if len(table_lines) < 2:
        return []
    headers = [strip_md_inline(c).lower() for c in table_lines[0].strip("|").split("|")]
    rows = []
    for ln in table_lines[1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if all(re.match(r"^:?-{2,}:?$", c) or not c for c in cells):
            continue
        row = {}
        for idx, h in enumerate(headers):
            row[h] = cells[idx] if idx < len(cells) else ""
        rows.append(row)
    return rows


def normalize_agent_key(raw):
    low = strip_md_inline(raw).lower()
    for key in ("red", "blue", "green", "yellow", "black", "main"):
        if re.search(r"\b%s\b" % key, low):
            return "main" if key == "black" else key
    return "main"


def make_agent_node(agent_key):
    key = "main" if agent_key == "black" else agent_key
    name, desc = AGENT_INFO.get(key, ("Black Agent", AGENT_INFO["main"][1]))
    return {
        "@type": "Organization",
        "@id": "urn:voltron:lion:%s" % key,
        "additionalType": "https://schema.org/SoftwareApplication",
        "name": name,
        "description": desc,
    }


def extract_file_paths(raw):
    text = (raw or "").strip()
    if not text or text.lower() in ("none", "n/a", "-", "\u2014", "(none)", "read-only"):
        return []
    # Prefer backticked paths when present; otherwise split on comma/semicolon.
    backticked = re.findall(r"`([^`]+)`", text)
    candidates = backticked if backticked else re.split(r"[,;]+", text)
    out = []
    for c in candidates:
        p = c.strip().strip("`").strip()
        if not p or p.lower() in ("none", "n/a", "-", "\u2014"):
            continue
        # Drop trailing parenthetical notes like "(read-only)" or "(new)"
        p = re.sub(r"\s*\([^)]*\)\s*$", "", p).strip()
        if p and p not in out:
            out.append(p)
    return out


def make_item_list(list_id, list_name, item_prefix, items):
    item_nodes = []
    refs = []
    for idx, text in enumerate(items, start=1):
        iid = "%s:%d" % (item_prefix, idx)
        refs.append({"@id": iid})
        item_nodes.append({
            "@type": "DefinedTerm",
            "@id": iid,
            "name": text[:80],
            "description": text,
            "inDefinedTermSet": {"@id": list_id},
        })
    list_node = {
        "@type": "ItemList",
        "@id": list_id,
        "name": list_name,
        "itemListElement": refs,
    }
    return list_node, item_nodes


def compile_brief(md_text, slug=None, date_str=None):
    title = parse_h1(md_text) or "ActionBoard Mission"
    sections = parse_sections(md_text)
    objective = parse_first_paragraph(find_section(sections, "objective")) or title
    resolved_slug = slugify(slug or title)
    pub_date = date_str or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    mission_id = "urn:voltron:mission:%s" % resolved_slug
    brief_id = "%s:brief" % mission_id

    scope_items = parse_bullets(find_section(sections, "scope"))
    # Avoid matching "out of scope" when searching "scope"
    for low, _raw, body in sections:
        if low.strip() == "scope":
            scope_items = parse_bullets(body)
            break
    out_of_scope_items = parse_bullets(find_section(sections, "out of scope", "out-of-scope"))
    criteria_items = parse_bullets(find_section(sections, "success criteria", "criteria"))
    constraint_items = parse_bullets(find_section(sections, "constraint"))

    graph = [
        {
            "@type": "Project",
            "@id": mission_id,
            "name": title,
            "description": objective,
            "identifier": resolved_slug,
            "startDate": pub_date,
            "subjectOf": [{"@id": brief_id}],
        },
        {
            "@type": "Report",
            "@id": brief_id,
            "name": "Mission Brief \u2014 %s" % title,
            "about": {"@id": mission_id},
            "datePublished": pub_date,
            "creator": {"@id": "urn:voltron:lion:main"},
            "abstract": objective,
            "mainEntity": {
                "@type": "ItemList",
                "itemListElement": [
                    {"@id": "%s:scope" % mission_id},
                    {"@id": "%s:out-of-scope" % mission_id},
                    {"@id": "%s:success-criteria" % mission_id},
                    {"@id": "%s:constraints" % mission_id},
                ],
            },
        },
        make_agent_node("main"),
    ]

    for suffix, name, item_suffix, items in (
        ("scope", "Scope", "scope", scope_items),
        ("out-of-scope", "Out of Scope", "out-of-scope", out_of_scope_items),
        ("success-criteria", "Success Criteria", "criterion", criteria_items),
        ("constraints", "Constraints", "constraint", constraint_items),
    ):
        list_node, item_nodes = make_item_list(
            "%s:%s" % (mission_id, suffix),
            name,
            "%s:%s" % (mission_id, item_suffix),
            items,
        )
        graph.append(list_node)
        graph.extend(item_nodes)

    return {"@context": SCHEMA_CTX, "@graph": graph}


def _load_project_from_jsonld(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for node in data.get("@graph") or []:
        if isinstance(node, dict) and node.get("@type") == "Project":
            return node
    return {}


def compile_plan(md_text, brief_path=None, slug=None, date_str=None):
    brief_project = _load_project_from_jsonld(brief_path)
    title = brief_project.get("name") or parse_h1(md_text) or "ActionBoard Mission"
    description = brief_project.get("description") or parse_first_paragraph(md_text) or title
    resolved_slug = slugify(slug or brief_project.get("identifier") or title)
    pub_date = date_str or brief_project.get("startDate") or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    mission_id = brief_project.get("@id") or ("urn:voltron:mission:%s" % resolved_slug)
    plan_id = "%s:plan" % mission_id
    sections = parse_sections(md_text)

    assign_rows = parse_markdown_table(find_section(sections, "assignment"))
    gap_rows = parse_markdown_table(find_section(sections, "skills gap", "skill gap"))
    risk_rows = parse_markdown_table(find_section(sections, "risk"))

    agents_used = ["main"]
    files_seen = {}
    main_refs = []
    action_nodes = []

    for idx, row in enumerate(assign_rows, start=1):
        aid = "%s:assignment:%d" % (mission_id, idx)
        main_refs.append({"@id": aid})
        agent_raw = row.get("agent") or row.get("lion") or "main"
        agent_key = normalize_agent_key(agent_raw)
        if agent_key not in agents_used:
            agents_used.append(agent_key)

        task = strip_md_inline(row.get("task") or row.get("description") or ("Assignment %d" % idx))
        acceptance = strip_md_inline(row.get("acceptance") or row.get("acceptance criteria") or "")
        files = extract_file_paths(row.get("files owned") or row.get("files") or "")
        depends = strip_md_inline(row.get("depends on") or "")

        action = {
            "@type": "Action",
            "@id": aid,
            "name": task,
            "description": task,
            "agent": {"@id": "urn:voltron:lion:%s" % agent_key},
            "actionStatus": "https://schema.org/PotentialActionStatus",
        }
        if files:
            action["object"] = [{"@id": "urn:voltron:file:%s" % p} for p in files]
            for p in files:
                files_seen.setdefault(p, {
                    "@type": "SoftwareSourceCode",
                    "@id": "urn:voltron:file:%s" % p,
                    "name": p,
                })
        if acceptance:
            action["result"] = [{
                "@type": "DefinedTerm",
                "name": "acceptance",
                "description": acceptance,
            }]
        if depends and depends.lower() not in ("none", "n/a", "-", "\u2014"):
            action["additionalProperty"] = [{
                "@type": "PropertyValue",
                "name": "dependsOn",
                "value": depends,
            }]
        action_nodes.append(action)

    gap_nodes = []
    for idx, row in enumerate(gap_rows, start=1):
        gid = "%s:gap:%d" % (mission_id, idx)
        main_refs.append({"@id": gid})
        cap = strip_md_inline(row.get("capability") or ("Capability %d" % idx))
        status = strip_md_inline(row.get("status") or "covered")
        notes = strip_md_inline(row.get("notes") or "")
        props = [{"@type": "PropertyValue", "name": "status", "value": status}]
        if notes:
            props.append({"@type": "PropertyValue", "name": "notes", "value": notes})
        gap_nodes.append({
            "@type": "DefinedTerm",
            "@id": gid,
            "name": cap,
            "additionalProperty": props,
        })

    risk_nodes = []
    for idx, row in enumerate(risk_rows, start=1):
        rid = "%s:risk:%d" % (mission_id, idx)
        main_refs.append({"@id": rid})
        cat = strip_md_inline(row.get("category") or "technical").lower()
        risk_desc = strip_md_inline(row.get("risk") or ("Risk %d" % idx))
        sev = strip_md_inline(row.get("severity") or "M").upper()
        mit = strip_md_inline(row.get("mitigation") or "accept and monitor")
        risk_nodes.append({
            "@type": "Thing",
            "@id": rid,
            "additionalType": "Risk",
            "name": risk_desc[:80],
            "description": risk_desc,
            "additionalProperty": [
                {"@type": "PropertyValue", "name": "category", "value": cat},
                {"@type": "PropertyValue", "name": "severity", "value": sev},
                {"@type": "PropertyValue", "name": "mitigation", "value": mit},
            ],
        })

    members = [{"@id": "urn:voltron:lion:%s" % k} for k in agents_used if k != "main"]
    subject_of = []
    if brief_project:
        subject_of.append({"@id": "%s:brief" % mission_id})
    subject_of.append({"@id": plan_id})

    project_node = {
        "@type": "Project",
        "@id": mission_id,
        "name": title,
        "description": description,
        "identifier": resolved_slug,
        "startDate": pub_date,
        "subjectOf": subject_of,
    }
    if members:
        project_node["member"] = members

    plan_node = {
        "@type": "Report",
        "@id": plan_id,
        "name": "Mission Plan \u2014 %s" % title,
        "about": {"@id": mission_id},
        "datePublished": pub_date,
        "creator": {"@id": "urn:voltron:lion:main"},
        "abstract": "%d assignments, %d skills-gap entries, %d risks. Awaiting go/no-go." % (
            len(action_nodes), len(gap_nodes), len(risk_nodes)
        ),
        "mainEntity": {"@type": "ItemList", "itemListElement": main_refs},
    }

    graph = [project_node, plan_node]
    graph.extend(make_agent_node(k) for k in agents_used)
    graph.extend(files_seen.values())
    graph.extend(action_nodes)
    graph.extend(gap_nodes)
    graph.extend(risk_nodes)

    return {"@context": SCHEMA_CTX, "@graph": graph}


def _map_outcome_status(raw_status):
    low = strip_md_inline(raw_status).lower()
    if any(w in low for w in ("done", "shipped", "complete", "pass", "merged")):
        return "https://schema.org/CompletedActionStatus"
    if any(w in low for w in ("block", "fail", "error")):
        return "https://schema.org/FailedActionStatus"
    if any(w in low for w in ("active", "progress", "running")):
        return "https://schema.org/ActiveActionStatus"
    return "https://schema.org/PotentialActionStatus"


def _maturity_nodes_from_registry(registry_path, slug, mission_id):
    if not registry_path or not os.path.isfile(registry_path):
        return []
    with open(registry_path, encoding="utf-8") as fh:
        reg = json.load(fh)
    raw_actions = reg.get("actions") or []
    if isinstance(raw_actions, dict):
        action_entries = [(aid, entry) for aid, entry in raw_actions.items() if isinstance(entry, dict)]
    elif isinstance(raw_actions, list):
        action_entries = [(entry.get("id") or "action", entry) for entry in raw_actions if isinstance(entry, dict)]
    else:
        action_entries = []

    nodes = []
    idx = 0
    for action_id, entry in action_entries:
        runs = [r for r in (entry.get("runs") or []) if isinstance(r, dict) and r.get("mission") == slug]
        for run in runs:
            idx += 1
            stages = run.get("stages") or {}
            props = [{"@type": "PropertyValue", "name": "actionId", "value": action_id}]
            all_pass = True
            for st in ("orchestrator", "data", "analysis", "action", "defense"):
                if st in stages:
                    passed = stages[st] is True or str(stages[st]).lower() == "pass"
                    props.append({"@type": "PropertyValue", "name": "stage:%s" % st, "value": "pass" if passed else "fail"})
                    if not passed:
                        all_pass = False
                else:
                    all_pass = False
            first_attempt = run.get("first_attempt", not run.get("retried"))
            clean = all_pass and bool(first_attempt) and run.get("provenance", "scored") == "scored"
            props.append({"@type": "PropertyValue", "name": "cleanRun", "value": clean})
            if entry.get("risk_tier"):
                props.append({"@type": "PropertyValue", "name": "riskTier", "value": entry["risk_tier"]})
            run_id = str(run.get("run_id") or "")
            m_num = re.search(r"-(\d+)$", run_id)
            assign_num = int(m_num.group(1)) if m_num else idx
            m_id = "%s:maturity:%d" % (mission_id, assign_num)
            node = {
                "@type": "Thing",
                "@id": m_id,
                "additionalType": "MaturityProgress",
                "name": action_id,
                "about": {"@id": "%s:assignment:%d" % (mission_id, assign_num)},
                "additionalProperty": props,
            }
            nodes.append(node)
    return nodes


def compile_report(md_text, plan_path=None, registry_path=None, slug=None, date_str=None):
    pub_date = date_str or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    sections = parse_sections(md_text)
    outcome_rows = parse_markdown_table(find_section(sections, "outcome"))

    plan_graph = []
    if plan_path and os.path.isfile(plan_path):
        with open(plan_path, encoding="utf-8") as fh:
            plan_graph = json.load(fh).get("@graph") or []

    if plan_graph:
        graph = json.loads(json.dumps(plan_graph))  # deep copy
        project_node = next((n for n in graph if n.get("@type") == "Project"), None)
        resolved_slug = slugify(slug or (project_node or {}).get("identifier") or parse_h1(md_text))
        mission_id = (project_node or {}).get("@id") or ("urn:voltron:mission:%s" % resolved_slug)
        title = (project_node or {}).get("name") or parse_h1(md_text) or "ActionBoard Mission"
    else:
        title = parse_h1(md_text) or "ActionBoard Mission"
        resolved_slug = slugify(slug or title)
        mission_id = "urn:voltron:mission:%s" % resolved_slug
        project_node = {
            "@type": "Project",
            "@id": mission_id,
            "name": title,
            "description": parse_first_paragraph(md_text) or title,
            "identifier": resolved_slug,
            "startDate": pub_date,
            "subjectOf": [],
        }
        graph = [project_node, make_agent_node("main")]

    report_id = "%s:report" % mission_id
    if project_node is not None:
        project_node["endDate"] = pub_date
        subs = project_node.setdefault("subjectOf", [])
        if not any(isinstance(s, dict) and s.get("@id") == report_id for s in subs):
            subs.append({"@id": report_id})

    actions = [n for n in graph if n.get("@type") == "Action"]
    agents_present = {n.get("@id") for n in graph if n.get("@type") == "Organization"}

    if not actions and outcome_rows:
        for idx, row in enumerate(outcome_rows, start=1):
            agent_key = normalize_agent_key(row.get("agent") or row.get("lion") or "main")
            agent_urn = "urn:voltron:lion:%s" % agent_key
            if agent_urn not in agents_present:
                graph.append(make_agent_node(agent_key))
                agents_present.add(agent_urn)
            status_uri = _map_outcome_status(row.get("status") or row.get("outcome") or "done")
            summary = strip_md_inline(row.get("summary") or row.get("notes") or row.get("result") or row.get("evidence") or "")
            task = strip_md_inline(row.get("task") or row.get("assignment") or ("Assignment %d" % idx))
            act = {
                "@type": "Action",
                "@id": "%s:assignment:%d" % (mission_id, idx),
                "name": task,
                "agent": {"@id": agent_urn},
                "actionStatus": status_uri,
            }
            if summary:
                act["result"] = [{"@type": "DefinedTerm", "name": "outcome", "description": summary}]
            if status_uri == "https://schema.org/FailedActionStatus":
                act["error"] = summary or "Blocked"
            graph.append(act)
            actions.append(act)
    else:
        for idx, act in enumerate(actions):
            if idx < len(outcome_rows):
                row = outcome_rows[idx]
                status_uri = _map_outcome_status(row.get("status") or row.get("outcome") or "done")
                summary = strip_md_inline(row.get("summary") or row.get("notes") or row.get("result") or row.get("evidence") or "")
                act["actionStatus"] = status_uri
                res_list = act.get("result")
                if not isinstance(res_list, list):
                    res_list = []
                if summary:
                    res_list = [r for r in res_list if not (isinstance(r, dict) and r.get("name") == "outcome")]
                    res_list.append({"@type": "DefinedTerm", "name": "outcome", "description": summary})
                    act["result"] = res_list
                if status_uri == "https://schema.org/FailedActionStatus":
                    act["error"] = summary or "Blocked"

    maturity_nodes = _maturity_nodes_from_registry(registry_path, resolved_slug, mission_id)
    existing_ids = {n.get("@id") for n in graph if isinstance(n, dict)}
    for mn in maturity_nodes:
        # Link maturity node to an existing assignment if present
        if mn["about"]["@id"] not in existing_ids and actions:
            mn["about"] = {"@id": actions[0]["@id"]}
        if mn["@id"] not in existing_ids:
            graph.append(mn)
            existing_ids.add(mn["@id"])

    completed = sum(1 for a in actions if a.get("actionStatus") == "https://schema.org/CompletedActionStatus")
    failed = sum(1 for a in actions if a.get("actionStatus") == "https://schema.org/FailedActionStatus")
    report_refs = [{"@id": a["@id"]} for a in actions] + [{"@id": m["@id"]} for m in maturity_nodes]

    report_node = {
        "@type": "Report",
        "@id": report_id,
        "name": "Mission Report \u2014 %s" % title,
        "about": {"@id": mission_id},
        "datePublished": pub_date,
        "creator": {"@id": "urn:voltron:lion:main"},
        "abstract": "%d/%d assignments completed, %d blocked." % (completed, len(actions), failed),
        "mainEntity": {"@type": "ItemList", "itemListElement": report_refs},
    }
    graph.insert(1, report_node)

    return {"@context": SCHEMA_CTX, "@graph": graph}


def validate_jsonld(data, known_ids=None):
    errors = []
    if not isinstance(data, dict):
        return ["root value must be a JSON object"]
    if data.get("@context") != SCHEMA_CTX:
        errors.append("@context must be %r" % SCHEMA_CTX)
    graph = data.get("@graph")
    if not isinstance(graph, list) or not graph:
        return errors + ["@graph must be a non-empty array"]

    defined_ids = set(known_ids or ())
    for node in graph:
        if isinstance(node, dict) and node.get("@id"):
            defined_ids.add(node["@id"])

    def walk_refs(obj, parent_id):
        if isinstance(obj, dict):
            if set(obj.keys()) == {"@id"}:
                ref = obj["@id"]
                if ref.startswith("urn:voltron:lion:"):
                    lion = ref.split("urn:voltron:lion:", 1)[1]
                    if lion not in VALID_LIONS:
                        errors.append("invalid agent URN %r in %s" % (ref, parent_id))
                elif ref not in defined_ids:
                    errors.append("unresolved @id reference %r in %s" % (ref, parent_id))
            else:
                for v in obj.values():
                    walk_refs(v, parent_id)
        elif isinstance(obj, list):
            for item in obj:
                walk_refs(item, parent_id)

    for node in graph:
        if not isinstance(node, dict):
            errors.append("non-object item in @graph")
            continue
        nid = node.get("@id") or "<anonymous>"
        if node.get("@type") == "Action":
            status = node.get("actionStatus")
            if status not in VALID_ACTION_STATUSES:
                errors.append("invalid actionStatus %r on %s" % (status, nid))
        walk_refs(node, nid)

    return errors


def _write_jsonld(path, data):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_brief = sub.add_parser("brief", help="compile mission-brief.md to mission-brief.jsonld")
    p_brief.add_argument("--md", required=True)
    p_brief.add_argument("--out", required=True)
    p_brief.add_argument("--slug")
    p_brief.add_argument("--date")

    p_plan = sub.add_parser("plan", help="compile mission-plan.md to mission-plan.jsonld")
    p_plan.add_argument("--md", required=True)
    p_plan.add_argument("--out", required=True)
    p_plan.add_argument("--brief")
    p_plan.add_argument("--slug")
    p_plan.add_argument("--date")

    p_rep = sub.add_parser("report", help="compile mission-report.md to mission-report.jsonld")
    p_rep.add_argument("--md", required=True)
    p_rep.add_argument("--out", required=True)
    p_rep.add_argument("--plan")
    p_rep.add_argument("--registry")
    p_rep.add_argument("--slug")
    p_rep.add_argument("--date")

    p_val = sub.add_parser("validate", help="validate one or more .jsonld files or a mission directory")
    p_val.add_argument("paths", nargs="+")

    args = ap.parse_args(argv)

    if args.cmd == "brief":
        with open(args.md, encoding="utf-8") as fh:
            md = fh.read()
        data = compile_brief(md, slug=args.slug or infer_slug_from_path(args.md), date_str=args.date or infer_date_from_path(args.md))
        errs = validate_jsonld(data)
        if errs:
            sys.stderr.write("compile_jsonld: validation failed:\n  " + "\n  ".join(errs) + "\n")
            return 2
        _write_jsonld(args.out, data)
        print("Compiled %s (%d nodes)" % (args.out, len(data["@graph"])))
        return 0

    if args.cmd == "plan":
        with open(args.md, encoding="utf-8") as fh:
            md = fh.read()
        brief = args.brief or os.path.join(os.path.dirname(os.path.abspath(args.md)), "mission-brief.jsonld")
        data = compile_plan(md, brief_path=brief if os.path.isfile(brief) else None, slug=args.slug or infer_slug_from_path(args.md), date_str=args.date or infer_date_from_path(args.md))
        known = set()
        if os.path.isfile(brief):
            with open(brief, encoding="utf-8") as fh:
                for n in (json.load(fh).get("@graph") or []):
                    if isinstance(n, dict) and n.get("@id"):
                        known.add(n["@id"])
        errs = validate_jsonld(data, known_ids=known)
        if errs:
            sys.stderr.write("compile_jsonld: validation failed:\n  " + "\n  ".join(errs) + "\n")
            return 2
        _write_jsonld(args.out, data)
        print("Compiled %s (%d nodes)" % (args.out, len(data["@graph"])))
        return 0

    if args.cmd == "report":
        with open(args.md, encoding="utf-8") as fh:
            md = fh.read()
        plan = args.plan or os.path.join(os.path.dirname(os.path.abspath(args.md)), "mission-plan.jsonld")
        data = compile_report(
            md,
            plan_path=plan if os.path.isfile(plan) else None,
            registry_path=args.registry,
            slug=args.slug or infer_slug_from_path(args.md),
            date_str=args.date or infer_date_from_path(args.md),
        )
        known = set()
        brief = os.path.join(os.path.dirname(os.path.abspath(args.md)), "mission-brief.jsonld")
        if os.path.isfile(brief):
            with open(brief, encoding="utf-8") as fh:
                for n in (json.load(fh).get("@graph") or []):
                    if isinstance(n, dict) and n.get("@id"):
                        known.add(n["@id"])
        errs = validate_jsonld(data, known_ids=known)
        if errs:
            sys.stderr.write("compile_jsonld: validation failed:\n  " + "\n  ".join(errs) + "\n")
            return 2
        _write_jsonld(args.out, data)
        print("Compiled %s (%d nodes)" % (args.out, len(data["@graph"])))
        return 0

    if args.cmd == "validate":
        files = []
        for p in args.paths:
            if os.path.isdir(p):
                for name in sorted(os.listdir(p)):
                    if name.endswith(".jsonld"):
                        files.append(os.path.join(p, name))
            else:
                files.append(p)
        docs = []
        all_ids = set()
        for f in files:
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
            docs.append((f, doc))
            for n in (doc.get("@graph") or []):
                if isinstance(n, dict) and n.get("@id"):
                    all_ids.add(n["@id"])
        rc = 0
        for f, doc in docs:
            errs = validate_jsonld(doc, known_ids=all_ids)
            if errs:
                rc = 2
                sys.stderr.write("%s: INVALID\n  %s\n" % (f, "\n  ".join(errs)))
            else:
                print("%s: OK (%d nodes)" % (f, len(doc["@graph"])))
        return rc

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
