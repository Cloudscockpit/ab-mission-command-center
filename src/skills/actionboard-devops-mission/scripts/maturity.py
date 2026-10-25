#!/usr/bin/env python3
"""Record scored mission runs and render the Maturity & Progress Summary.

Every number comes from gate_check.py (same tiers, thresholds, 20-run window,
90-day staleness, clean-run rule), so the summary in a mission report can never
disagree with the gate that decides execution mode.

Record one scored run per action at the end of a mission:

    python maturity.py record --registry .actionboard/registry.json \\
        --action deploy-api --mission add-health-endpoint --run-id add-health-endpoint-1 \\
        --mode actionlist --stages orchestrator=pass,data=pass,analysis=pass,action=pass,defense=fail \\
        [--name "Deploy API" --risk-tier T2 --end-condition "..."]   # first time only
        [--retried] [--session ID] [--model M] [--target opencode] [--notes "..."]

Render the summary for every action a mission touched:

    python maturity.py summary --registry .actionboard/registry.json \\
        --mission add-health-endpoint --operator-level L3 [--json]

The operator level is never inferred: pass --operator-level, or set
"operator_level" in .actionboard/config.json next to the registry.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate_check as gate  # noqa: E402

STAGE_LABELS = [("orchestrator", "Orchestrator"), ("data", "Data"), ("analysis", "Analysis"),
                ("action", "Action"), ("defense", "Defense/Audit")]
MODES = ["guided", "actionlist", "autonomous"]
MODE_LABELS = {"guided": "Guided", "actionlist": "Actionlist", "autonomous": "Autonomous"}


# ---------------------------------------------------------------- registry io

def load(path):
    if not os.path.exists(path):
        return {"registry_version": "1", "actions": []}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"actions": data}
    data.setdefault("actions", [])
    return data


def save(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def operator_level(raw, registry_path):
    if raw:
        return gate.parse_level(raw)
    config = os.path.join(os.path.dirname(os.path.abspath(registry_path)), "config.json")
    if os.path.exists(config):
        with open(config, encoding="utf-8") as fh:
            value = json.load(fh).get("operator_level")
        if value:
            return gate.parse_level(value)
    raise SystemExit("Operator level unknown. Ask the operator for their certified level (L1-L7) "
                     "and pass --operator-level, or set operator_level in .actionboard/config.json. "
                     "Never assume it.")


# ---------------------------------------------------------------- recording

def parse_stages(text):
    stages = {}
    for part in text.split(","):
        if not part.strip():
            continue
        name, _, value = part.partition("=")
        name, value = name.strip().lower(), value.strip().lower()
        if name in ("defense/audit", "audit"):
            name = "defense"
        if name not in gate.STAGES:
            raise SystemExit("unknown stage %r; use %s" % (name, ", ".join(gate.STAGES)))
        if value not in ("pass", "fail", "true", "false"):
            raise SystemExit("stage %s must be pass or fail, got %r" % (name, value))
        stages[name] = value in ("pass", "true")
    # A stage that was not scored is a failure, not absent.
    return {s: stages.get(s, False) for s in gate.STAGES}


def record(args):
    data = load(args.registry)
    action = next((a for a in data["actions"] if a.get("id") == args.action), None)
    if action is None:
        missing = [f for f in ("name", "risk_tier", "end_condition") if not getattr(args, f)]
        if missing:
            raise SystemExit("Action %r is not registered. Register it with --%s." % (
                args.action, ", --".join(m.replace("_", "-") for m in missing)))
        action = {"id": args.action, "name": args.name, "risk_tier": args.risk_tier.upper(),
                  "end_condition": args.end_condition, "missions": [], "runs": []}
        data["actions"].append(action)
    if any(r.get("run_id") == args.run_id for r in action.get("runs", [])):
        raise SystemExit("Run %r is already recorded for %s; runs are append-only." % (args.run_id, args.action))

    stages = parse_stages(args.stages)
    if args.retried:
        stages["action"] = False  # retry-to-green scores the stage as failed
    run = {"run_id": args.run_id,
           "completed_at": args.completed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "mode": args.mode, "stages": stages, "first_attempt": not args.retried,
           "provenance": "scored"}
    if args.session:
        run["session_id"] = args.session
    env = {k: v for k, v in (("model", args.model), ("target", args.target)) if v}
    if env:
        run["environment"] = env
    if args.notes:
        run["notes"] = args.notes
    if args.mission:
        run["mission"] = args.mission
    action.setdefault("runs", []).append(run)
    if args.mission and args.mission not in action.setdefault("missions", []):
        action["missions"].append(args.mission)
    save(args.registry, data)
    print("recorded %s for %s: %s" % (args.run_id, args.action,
                                      ", ".join("%s=%s" % (s, "pass" if v else "fail") for s, v in stages.items())))
    return 0


# ---------------------------------------------------------------- progress

def runs_to_reach(runs, stage, threshold):
    """How many more passing runs until `stage` meets threshold in the window."""
    sim = list(gate.window_runs(runs))
    for n in range(1, gate.SCORING_WINDOW + 1):
        sim = (sim + [{"stages": {s: True for s in gate.STAGES}, "provenance": "scored"}])[-gate.SCORING_WINDOW:]
        if gate.stage_rates(sim)[stage] >= threshold:
            return n
    return gate.SCORING_WINDOW


def level_for_tier(tier_n):
    """Lowest operator level whose autonomy ceiling covers this tier."""
    return min(lvl for lvl, cap in gate.AUTONOMY_CEILING.items() if cap >= tier_n)


def next_milestone(action, level, result):
    tier = result["tier"]
    if tier not in gate.TIER_RULES:
        return "Classify the action's risk tier (T1-T4) before it can earn any autonomy."
    threshold, min_runs, min_level = gate.TIER_RULES[tier]
    ceiling = gate.AUTONOMY_CEILING[level]
    if tier == "T4":
        if level < min_level:
            return "T4 needs an L%d operator even for human-approved runs; it never becomes autonomous." % min_level
        return "None: T4 never becomes autonomous. Every run keeps a human go/no-go."
    if level < min_level:
        return "Operator certification L%d or above is required for %s." % (min_level, tier)
    runs = gate.window_runs(action.get("runs", []))
    clean = result["clean_runs"]
    if not runs:
        return "Complete the first scored run in Guided mode."
    if action.get("regressed_at"):
        return "Regression recorded: %d clean run(s) at threshold to re-qualify (%d/%d)." % (
            max(min_runs - clean, 0), clean, min_runs)
    rates = result["stage_rates"]
    failing = {s: r for s, r in rates.items() if r < threshold}
    if failing:
        parts = ["%s %.0f%% → %.0f%% (≈%d more passing run(s))" % (
            dict(STAGE_LABELS)[s], r * 100, threshold * 100, runs_to_reach(action["runs"], s, threshold))
            for s, r in sorted(failing.items(), key=lambda kv: kv[1])]
        return "Raise " + "; ".join(parts) + ", then reach %d clean runs to unlock Autonomous." % min_runs
    if clean < min_runs:
        unlock = "Autonomous" if gate.tier_number(tier) <= ceiling else \
            "eligibility (operator certification L%d is also needed to run it autonomously)" % (
                level_for_tier(gate.tier_number(tier)))
        return "%d more clean run(s) (%d/%d) to unlock %s." % (min_runs - clean, clean, min_runs, unlock)
    if gate.tier_number(tier) > ceiling:
        need = level_for_tier(gate.tier_number(tier))
        return "Gate met; operator certification L%d is required to run %s autonomously." % (need, tier)
    return ("Autonomous unlocked. Keep every stage at %.0f%% or above over the last %d runs "
            "(%d days) to keep it." % (threshold * 100, gate.SCORING_WINDOW, gate.STALENESS_DAYS))


def progress(action, level, run_id=None):
    result = gate.evaluate(action, level)
    runs = action.get("runs", [])
    this = next((r for r in runs if r.get("run_id") == run_id), None) if run_id else (runs[-1] if runs else None)
    stages = (this or {}).get("stages", {})
    tier = result["tier"]
    rule = gate.TIER_RULES.get(tier)
    clean_this = bool(this) and this.get("provenance") != "backfilled" and \
        all(stages.get(s) is True for s in gate.STAGES)
    return {
        "action_id": action.get("id"), "name": action.get("name"), "tier": tier,
        "run_id": (this or {}).get("run_id"),
        "this_run": {s: stages.get(s) is True for s in gate.STAGES},
        "stage_rates": result["stage_rates"],
        "threshold": rule[0] if rule else None,
        "clean_run": clean_this,
        "clean_runs": result["clean_runs"],
        "clean_runs_required": rule[1] if rule else None,
        "window_size": result["window_size"],
        "mode": result["verdict"],
        "gate_reason": result["reason"],
        "next_milestone": next_milestone(action, level, result),
    }


def _stage_cell(p, stage):
    mark = "✅ pass" if p["this_run"][stage] else "❌ fail"
    rate = p["stage_rates"].get(stage)
    return mark if rate is None or not p["window_size"] else "%s · %.0f%%" % (mark, rate * 100)


def _mode_cell(mode):
    return " → ".join("**%s**" % MODE_LABELS[m] if m == mode else MODE_LABELS[m] for m in MODES)


def markdown(rows, level, mission):
    out = ["## Maturity & Progress Summary", "",
           "Mission `%s` · Operator L%d · Scoring window: last %d runs within %d days · "
           "Source: `.actionboard/registry.json` via `gate_check.py`." % (
               mission, level, gate.SCORING_WINDOW, gate.STALENESS_DAYS), "",
           "Stage cells show this run's result, then the stage's pass rate across the scoring window.", "",
           "| Action | Tier (threshold) | " + " | ".join(label for _, label in STAGE_LABELS)
           + " | Clean Run | Clean runs | Execution mode | Next milestone |",
           "|---" * (9 + 2) + "|"]
    for p in rows:
        threshold = "%s (≥%.0f%%)" % (p["tier"], p["threshold"] * 100) if p["threshold"] else p["tier"]
        clean_req = "%d/%d" % (p["clean_runs"], p["clean_runs_required"]) if p["clean_runs_required"] \
            else "%d (T4: never autonomous)" % p["clean_runs"]
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            "%s (`%s`)" % (p["name"], p["action_id"]), threshold,
            " | ".join(_stage_cell(p, s) for s in gate.STAGES),
            "Yes" if p["clean_run"] else "No — failed: " + ", ".join(
                dict(STAGE_LABELS)[s] for s in gate.STAGES if not p["this_run"][s]),
            clean_req, _mode_cell(p["mode"]), p["next_milestone"]))
    if not rows:
        out.append("| _No actions were scored in this mission._ |" + " |" * 10)
    return "\n".join(out) + "\n"


def summary(args):
    level = operator_level(args.operator_level, args.registry)
    data = load(args.registry)
    actions = [a for a in data["actions"] if not args.mission or args.mission in a.get("missions", [])]
    rows = []
    for a in actions:
        run_id = next((r["run_id"] for r in reversed(a.get("runs", []))
                       if not args.mission or r.get("mission") == args.mission), None)
        rows.append(progress(a, level, run_id))
    if args.json:
        json.dump({"operator_level": level, "mission": args.mission, "actions": rows}, sys.stdout,
                  indent=2, ensure_ascii=False)
        print()
    else:
        sys.stdout.write(markdown(rows, level, args.mission or "all"))
    return 0


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="append one scored run for an action")
    rec.add_argument("--registry", default=".actionboard/registry.json")
    rec.add_argument("--action", required=True, help="action id")
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--mission", help="mission slug; tags the action and the run")
    rec.add_argument("--mode", required=True, choices=["guided", "actionlist", "formation"])
    rec.add_argument("--stages", required=True, help="orchestrator=pass,data=pass,analysis=pass,action=pass,defense=pass")
    rec.add_argument("--retried", action="store_true", help="the run only went green on retry")
    rec.add_argument("--completed-at", help="ISO timestamp (default: now, UTC)")
    rec.add_argument("--session")
    rec.add_argument("--model")
    rec.add_argument("--target", help="CLI the run happened in, e.g. opencode")
    rec.add_argument("--notes")
    rec.add_argument("--name", help="register: action name")
    rec.add_argument("--risk-tier", choices=["T1", "T2", "T3", "T4", "t1", "t2", "t3", "t4"])
    rec.add_argument("--end-condition", help="register: verifiable end condition")
    summ = sub.add_parser("summary", help="render the Maturity & Progress Summary")
    summ.add_argument("--registry", default=".actionboard/registry.json")
    summ.add_argument("--mission")
    summ.add_argument("--operator-level", help="L1-L7 (else .actionboard/config.json)")
    summ.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return record(args) if args.cmd == "record" else summary(args)


if __name__ == "__main__":
    sys.exit(main())
