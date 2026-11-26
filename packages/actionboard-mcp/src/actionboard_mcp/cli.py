"""`ab`: the ActionBoard CLI over the same core as the MCP server. Prints one JSON object on stdout."""
import argparse
import json
import sys

from . import core


def build_parser():
    p = argparse.ArgumentParser(prog="ab", description="ActionBoard missions from the terminal (JSON output).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="login state and selected Pod/Board")
    s = sub.add_parser("login", help="sign in through the browser")
    s.add_argument("--provider", choices=core.PROVIDERS)
    s.add_argument("--timeout", type=int, default=300)
    sub.add_parser("logout", help="remove stored tokens")
    sub.add_parser("pods", help="list your Pods")
    s = sub.add_parser("boards", help="list Boards in a Pod")
    s.add_argument("--pod")
    s = sub.add_parser("select", help="save the active Pod and Board")
    s.add_argument("--pod", required=True)
    s.add_argument("--board", required=True)
    s.add_argument("--sync", choices=("ask", "auto", "off"))
    s = sub.add_parser("assigned", help="missions and invitations assigned to you")
    s.add_argument("--pod")
    s.add_argument("--board")
    s.add_argument("--invitation-status", choices=core.INVITATION_STATUSES)
    s = sub.add_parser("fetch", help="download a mission to docs/missions/")
    for flag in ("--mission-id", "--invitation-id", "--pod", "--board", "--plan-id", "--out-dir"):
        s.add_argument(flag)
    s.add_argument("--accept", action="store_true")
    s.add_argument("--start", action="store_true")
    s = sub.add_parser("submit", help="upload a local mission folder")
    for flag in ("--mission-dir", "--pod", "--board", "--mission-id", "--invitation-id"):
        s.add_argument(flag)
    s.add_argument("--status", choices=core.STATUSES)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--keep-old", action="store_true")
    s.add_argument("--skip-s3", action="store_true")
    s = sub.add_parser("progress", help="post a status change or comment")
    s.add_argument("--mission-dir")
    s.add_argument("--mission-id")
    s.add_argument("--status", choices=core.STATUSES, default="IN_PROGRESS")
    s.add_argument("--comment", default="")
    return p


def dispatch(a):
    return {
        "status": lambda: core.auth_status(),
        "login": lambda: core.login(provider=a.provider, timeout=a.timeout),
        "logout": lambda: core.logout(),
        "pods": lambda: core.list_pods(),
        "boards": lambda: core.list_boards(a.pod),
        "select": lambda: core.select_board(a.pod, a.board, sync=a.sync),
        "assigned": lambda: core.list_assigned(a.pod, a.board, a.invitation_status),
        "fetch": lambda: core.fetch_mission(a.mission_id, a.invitation_id, a.pod, a.board, a.plan_id, a.out_dir,
                                            a.accept, a.start),
        "submit": lambda: core.submit_mission(a.mission_dir, a.pod, a.board, a.mission_id, a.invitation_id, a.status,
                                              a.dry_run, a.keep_old, a.skip_s3),
        "progress": lambda: core.post_progress(a.mission_dir, a.mission_id, a.status, a.comment),
    }[a.cmd]()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = dispatch(args)
    except core.ActionBoardError as exc:
        sys.stderr.write("ab: %s\n" % exc)
        return 3 if isinstance(exc, core.AuthRequiredError) else 1
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
