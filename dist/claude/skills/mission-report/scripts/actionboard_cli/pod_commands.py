"""ActionBoard CLI: pod service commands (actionlist, action, goal, files)."""
import json
import re
import sys

_CTRL_RE = re.compile(u"[\x00-\x1f\x7f-\x9f\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def _clean(value):
    """Strip control characters from server-supplied text before printing it."""
    return _CTRL_RE.sub(" ", "" if value is None else str(value))


def _split_tags(value):
    if value is None:
        return None
    return [t.strip() for t in value.split(",") if t.strip()]


def _context(args, opener):
    from .auth import resolve_settings
    from .commands import _resolve_pod_token_and_profile
    from .common import fail
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    pod, tok, _profile = _resolve_pod_token_and_profile(
        settings, None, pod_arg=getattr(args, "pod", None), interactive=interactive, opener=opener
    )
    board = getattr(args, "board", None) or settings["cfg"].get("board_id")
    if not board:
        fail("no board selected; pass --board <id> or run the ab-login skill to pick a default board.")
    return settings, tok, pod, board


def _emit(args, data, human):
    from .common import info
    if getattr(args, "json", False):
        info(json.dumps(data, indent=2))
    else:
        human()


def _line(*cols):
    from .common import info
    info("  ".join(_clean(c) for c in cols))


def _confirm_delete(args, label):
    from .common import fail
    sys.stderr.write("Delete  %s\n" % _clean(label))
    if getattr(args, "yes", False):
        return
    if getattr(args, "no_input", False) or not sys.stdin.isatty():
        fail("refusing to delete without confirmation; pass --yes to confirm.")
    try:
        sys.stderr.write("Delete this? [y/N] ")
        sys.stderr.flush()
        answer = input()
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        fail("delete cancelled.")


def _show_record(rec, keys):
    for key in keys:
        if rec.get(key) not in (None, "", []):
            _line("%-18s" % key, rec.get(key))


# --------------------------------------------------------------------------- ActionLists

def _list_fields(args):
    return {
        "action": getattr(args, "title", None),
        "actionListStatus": getattr(args, "status", None),
        "Context": getattr(args, "context", None),
        "notes": getattr(args, "notes", None),
        "Tags": _split_tags(getattr(args, "tags", None)),
        "isImportant": True if getattr(args, "important", False) else None,
        "isUrgent": True if getattr(args, "urgent", False) else None,
        "dueDate": getattr(args, "due", None),
        "startDate": getattr(args, "start", None),
    }


def cmd_actionlist(args, opener=None):
    from . import pod_services as svc
    from .common import fail
    settings, tok, _pod, board = _context(args, opener)
    verb = args.verb
    if verb == "list":
        page = svc.list_actionlists(settings, tok, board, status=args.status, limit=args.limit,
                                    next_token=args.next_token, opener=opener)

        def human():
            if not page["items"]:
                _line("No action lists found.")
            for r in page["items"]:
                _line("%-38s" % r.get("id"), "%-18s" % r.get("actionListStatus"), r.get("action"))
            if page["nextToken"]:
                _line("next-token:", page["nextToken"])
        _emit(args, page, human)
    elif verb == "show":
        rec = svc.find_actionlist(settings, tok, board, args.id, opener=opener)
        if not rec:
            fail("action list %s not found on board %s" % (args.id, board))
        _emit(args, rec, lambda: _show_record(
            rec, ("id", "action", "actionListStatus", "Context", "notes", "Tags", "dueDate",
                  "startDate", "isImportant", "isUrgent", "updatedAt")))
    elif verb == "create":
        rec = svc.create_actionlist(settings, tok, board, _list_fields(args), opener=opener)
        _emit(args, rec, lambda: _line("created", rec.get("id"), rec.get("actionListStatus"), rec.get("action")))
    elif verb == "update":
        rec = svc.update_actionlist(settings, tok, board, args.id, _list_fields(args), opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("actionListStatus"), rec.get("action")))
    elif verb == "status":
        rec = svc.update_actionlist(settings, tok, board, args.id, {"actionListStatus": args.new_status},
                                    opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("actionListStatus"), rec.get("action")))
    elif verb == "delete":
        rec = svc.find_actionlist(settings, tok, board, args.id, opener=opener)
        if not rec:
            fail("action list %s not found on board %s" % (args.id, board))
        _confirm_delete(args, "action list %s  %s" % (rec.get("id"), rec.get("action")))
        res = svc.delete_actionlist(settings, tok, board, args.id, version=rec.get("_version"), opener=opener)
        _emit(args, res, lambda: _line("deleted", res.get("id"), res.get("action")))
    return 0


# --------------------------------------------------------------------------- Action items

def _action_fields(args):
    notes = getattr(args, "notes", None)
    return {
        "ActionItem": getattr(args, "item", None),
        "ActionStatus": getattr(args, "status", None),
        "prompt": getattr(args, "prompt", None),
        "Notes": [notes] if notes else None,
        "tags": _split_tags(getattr(args, "tags", None)),
        "isImportant": True if getattr(args, "important", False) else None,
        "isUrgent": True if getattr(args, "urgent", False) else None,
        "dueDate": getattr(args, "due", None),
        "startDate": getattr(args, "start", None),
    }


def cmd_action(args, opener=None):
    from . import pod_services as svc
    settings, tok, _pod, board = _context(args, opener)
    verb = args.verb
    if verb == "list":
        page = svc.list_actions(settings, tok, args.list, statuses=args.status, limit=args.limit,
                                next_token=args.next_token, opener=opener)

        def human():
            if not page["items"]:
                _line("No action items found.")
            for r in page["items"]:
                _line("%-38s" % r.get("id"), "%-18s" % r.get("ActionStatus"), r.get("ActionItem"))
            if page["nextToken"]:
                _line("next-token:", page["nextToken"])
        _emit(args, page, human)
    elif verb == "get":
        rec = svc.get_action(settings, tok, args.id, opener=opener)
        _emit(args, rec, lambda: _show_record(
            rec, ("id", "actionlistID", "ActionItem", "ActionStatus", "prompt", "Notes", "tags",
                  "dueDate", "startDate", "isImportant", "isUrgent", "updatedAt")))
    elif verb == "create":
        rec = svc.create_action(settings, tok, board, args.list, _action_fields(args), opener=opener)
        _emit(args, rec, lambda: _line("created", rec.get("id"), rec.get("ActionStatus"), rec.get("ActionItem")))
    elif verb == "update":
        rec = svc.update_action(settings, tok, board, args.id, _action_fields(args), opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("ActionStatus"), rec.get("ActionItem")))
    elif verb == "status":
        rec = svc.update_action(settings, tok, board, args.id, {"ActionStatus": args.new_status}, opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("ActionStatus"), rec.get("ActionItem")))
    elif verb == "delete":
        cur = svc.get_action(settings, tok, args.id, opener=opener)
        _confirm_delete(args, "action item %s  %s" % (cur.get("id"), cur.get("ActionItem")))
        res = svc.delete_action(settings, tok, board, args.id, opener=opener)
        _emit(args, res, lambda: _line("deleted", res.get("id"), res.get("ActionItem")))
    return 0


# --------------------------------------------------------------------------- Goals

def _goal_fields(args):
    return {
        "title": getattr(args, "title", None),
        "priority": getattr(args, "priority", None),
        "description": getattr(args, "description", None),
        "status": getattr(args, "status", None),
        "dueDate": getattr(args, "due", None),
        "startDate": getattr(args, "start", None),
    }


def cmd_goal(args, opener=None):
    from . import pod_services as svc
    from .common import warn
    settings, tok, _pod, board = _context(args, opener)
    verb = args.verb
    if verb == "list":
        page = svc.list_goals(settings, tok, board, limit=100, opener=opener)
        if page["nextToken"]:
            warn("more goals exist than the 100 shown; server-side paging is not available.")
        if args.status:
            page["items"] = [g for g in page["items"] if g.get("status") == args.status]

        def human():
            if not page["items"]:
                _line("No goals found.")
            for g in page["items"]:
                _line("%-38s" % g.get("id"), "%-12s" % g.get("status"), "%-7s" % g.get("priority"), g.get("title"))
        _emit(args, page, human)
    elif verb == "get":
        rec = svc.get_goal(settings, tok, board, args.id, opener=opener)
        _emit(args, rec, lambda: _show_record(
            rec, ("id", "title", "description", "priority", "status", "assignedUserId", "dueDate",
                  "startDate", "updatedAt")))
    elif verb == "create":
        fields = _goal_fields(args)
        title, priority = fields.pop("title"), fields.pop("priority")
        rec = svc.create_goal(settings, tok, board, title, priority, fields=fields,
                              user_id=args.user_id, opener=opener)
        _emit(args, rec, lambda: _line("created", rec.get("id"), rec.get("status"), rec.get("priority"), rec.get("title")))
    elif verb == "update":
        rec = svc.update_goal(settings, tok, board, args.id, _goal_fields(args), opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("status"), rec.get("priority"), rec.get("title")))
    elif verb == "status":
        rec = svc.update_goal(settings, tok, board, args.id, {"status": args.new_status}, opener=opener)
        _emit(args, rec, lambda: _line("updated", rec.get("id"), rec.get("status"), rec.get("priority"), rec.get("title")))
    elif verb == "delete":
        cur = svc.get_goal(settings, tok, board, args.id, opener=opener)
        _confirm_delete(args, "goal %s  %s" % (cur.get("id"), cur.get("title")))
        res = svc.delete_goal(settings, tok, board, args.id, opener=opener)
        _emit(args, res, lambda: _line("deleted", res.get("id"), res.get("title")))
    return 0


# --------------------------------------------------------------------------- Files

def cmd_files(args, opener=None):
    from . import pod_services as svc
    settings, tok, pod, board = _context(args, opener)
    verb = args.verb
    if verb == "folders":
        folders = svc.list_folders(settings, tok, board, opener=opener)

        def human():
            if not folders:
                _line("No folders found.")
            for f in folders:
                _line("%-38s" % f.get("id"), "%-38s" % (f.get("parentFolderId") or "-"), f.get("folderName"))
        _emit(args, folders, human)
    elif verb == "mkdir":
        rec = svc.create_folder(settings, tok, board, args.name, parent_folder_id=args.parent, opener=opener)
        _emit(args, rec, lambda: _line("created", rec.get("id"), rec.get("folderName")))
    elif verb == "list":
        files = svc.list_files(settings, tok, board, args.folder, opener=opener)

        def human():
            if not files:
                _line("No files found.")
            for f in files:
                _line("%-38s" % f.get("id"), "%10s" % (f.get("fileSize") if f.get("fileSize") is not None else ""),
                      f.get("fileName"))
        _emit(args, files, human)
    elif verb == "upload":
        rec = svc.upload_file(settings, tok, pod["podId"], board, args.folder, args.path,
                              note=args.note, tags=_split_tags(args.tags), opener=opener)
        _emit(args, rec, lambda: _line("uploaded", rec.get("id"), rec.get("fileName")))
    elif verb == "download":
        res = svc.download_file(settings, tok, args.file_id, args.out, overwrite=args.overwrite, opener=opener)
        _emit(args, res, lambda: _line("downloaded", res.get("id"), "%d bytes" % res.get("size", 0), res.get("path")))
    elif verb == "delete":
        cur = svc.get_file(settings, tok, args.file_id, opener=opener)
        _confirm_delete(args, "file %s  %s" % (cur.get("id"), cur.get("fileName")))
        res = svc.delete_file(settings, tok, args.file_id, opener=opener)
        _emit(args, res, lambda: _line("deleted", res.get("id"), res.get("fileName")))
    return 0


def run(handler, args, opener=None):
    """Run a handler, turning input errors into a clean non-zero exit."""
    from .common import fail
    try:
        return handler(args, opener=opener)
    except (ValueError, OSError) as exc:
        fail("%s %s failed: %s" % (args.subcommand, getattr(args, "verb", ""), exc))


HANDLERS = {
    "actionlist": cmd_actionlist,
    "action": cmd_action,
    "goal": cmd_goal,
    "files": cmd_files,
}


# --------------------------------------------------------------------------- parser

def register(sub, common_sub):
    from . import pod_services as svc

    def group(name, help_text):
        sp = sub.add_parser(name, parents=[common_sub], help=help_text)
        return sp.add_subparsers(dest="verb", required=True, metavar="VERB")

    def leaf(verbs, name, help_text, delete=False):
        sp = verbs.add_parser(name, parents=[common_sub], help=help_text)
        sp.add_argument("--pod", help="pod ID, slug, or name (default: from config)")
        sp.add_argument("--board", help="board ID (default: board_id from .actionboard/config.json)")
        sp.add_argument("--no-input", action="store_true", help="do not prompt interactively")
        sp.add_argument("--json", action="store_true", help="output JSON")
        if delete:
            sp.add_argument("--yes", action="store_true", help="confirm the delete without asking")
        return sp

    def dates(sp):
        sp.add_argument("--due", help="due date (ISO 8601)")
        sp.add_argument("--start", help="start date (ISO 8601)")

    def flags(sp):
        sp.add_argument("--tags", help="comma-separated tags")
        sp.add_argument("--important", action="store_true", help="mark important")
        sp.add_argument("--urgent", action="store_true", help="mark urgent")
        dates(sp)

    statuses = svc.ACTIONLIST_STATUSES

    al = group("actionlist", "list, show, create, update, and delete ActionLists on a board")
    sp = leaf(al, "list", "list ActionLists")
    sp.add_argument("--status", choices=statuses)
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--next-token")
    leaf(al, "show", "show one ActionList").add_argument("id")
    for verb in ("create", "update"):
        sp = leaf(al, verb, "%s an ActionList" % verb)
        if verb == "create":
            sp.add_argument("--title", required=True)
        else:
            sp.add_argument("id")
            sp.add_argument("--title")
        sp.add_argument("--status", choices=statuses)
        sp.add_argument("--context")
        sp.add_argument("--notes")
        flags(sp)
    sp = leaf(al, "status", "set an ActionList status")
    sp.add_argument("id")
    sp.add_argument("new_status", metavar="STATUS", choices=statuses)
    leaf(al, "delete", "delete an ActionList", delete=True).add_argument("id")

    ac = group("action", "list, get, create, update, and delete action items in an ActionList")
    sp = leaf(ac, "list", "list action items in an ActionList")
    sp.add_argument("--list", required=True, help="ActionList ID")
    sp.add_argument("--status", nargs="+", choices=statuses)
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--next-token")
    leaf(ac, "get", "get one action item").add_argument("id")
    for verb in ("create", "update"):
        sp = leaf(ac, verb, "%s an action item" % verb)
        if verb == "create":
            sp.add_argument("--list", required=True, help="ActionList ID")
            sp.add_argument("--item", required=True, help="action item text")
        else:
            sp.add_argument("id")
            sp.add_argument("--item", help="action item text")
        sp.add_argument("--status", choices=statuses)
        sp.add_argument("--prompt")
        sp.add_argument("--notes")
        flags(sp)
    sp = leaf(ac, "status", "set an action item status")
    sp.add_argument("id")
    sp.add_argument("new_status", metavar="STATUS", choices=statuses)
    leaf(ac, "delete", "delete an action item", delete=True).add_argument("id")

    gl = group("goal", "list, get, create, update, and delete Goals on a board")
    sp = leaf(gl, "list", "list Goals")
    sp.add_argument("--status", choices=svc.GOAL_STATUSES)
    leaf(gl, "get", "get one Goal").add_argument("id")
    for verb in ("create", "update"):
        sp = leaf(gl, verb, "%s a Goal" % verb)
        if verb == "create":
            sp.add_argument("--title", required=True)
            sp.add_argument("--priority", required=True, choices=svc.GOAL_PRIORITIES)
            sp.add_argument("--user-id", help="owner user ID (default: you)")
        else:
            sp.add_argument("id")
            sp.add_argument("--title")
            sp.add_argument("--priority", choices=svc.GOAL_PRIORITIES)
        sp.add_argument("--description")
        sp.add_argument("--status", choices=svc.GOAL_STATUSES)
        dates(sp)
    sp = leaf(gl, "status", "set a Goal status")
    sp.add_argument("id")
    sp.add_argument("new_status", metavar="STATUS", choices=svc.GOAL_STATUSES)
    leaf(gl, "delete", "delete a Goal", delete=True).add_argument("id")

    fl = group("files", "list folders and files, upload, download, and delete board files")
    leaf(fl, "folders", "list folders on the board")
    sp = leaf(fl, "mkdir", "create a folder")
    sp.add_argument("name")
    sp.add_argument("--parent", help="parent folder ID")
    leaf(fl, "list", "list files in a folder").add_argument("--folder", required=True, help="folder ID")
    sp = leaf(fl, "upload", "upload a file into a folder")
    sp.add_argument("path")
    sp.add_argument("--folder", required=True, help="folder ID")
    sp.add_argument("--note")
    sp.add_argument("--tags", help="comma-separated tags")
    sp = leaf(fl, "download", "download a file")
    sp.add_argument("file_id")
    sp.add_argument("--out", default=".", help="output directory (default: .)")
    sp.add_argument("--overwrite", action="store_true", help="replace an existing file")
    leaf(fl, "delete", "delete a file", delete=True).add_argument("file_id")
