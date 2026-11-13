"""CLI-agnostic OpenShell command analysis shared by guard.py and audit.py.

Commands are parsed into argv with shlex rather than substring-matched. The
shell strips quotes before the CLI ever sees them, so a guard that greps for
--all-workspaces misses --all-work"spaces", which runs identically. Parsing also
covers --flag=value, short flags, extra whitespace, operator chains (quote-aware),
`bash -c` / `cmd /c` wrappers, common command wrappers, and VAR=value prefixes.

The guard is defense in depth, not a sandbox. It fails CLOSED ("ask") whenever
an `openshell` token appears that it cannot attribute to a parsed invocation,
when an invocation uses shell expansion, and when the text cannot be parsed.
What it cannot see at all (text assembled at runtime, e.g. `$a$b`, encoded
payloads) is out of scope; see docs/capability-matrix.md.

Standard library only; Python 3.9+.
"""

import re
import shlex

ALLOW = "allow"
ASK = "ask"
DENY = "deny"
_RANK = {ALLOW: 0, ASK: 1, DENY: 2}

CRED = {"TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS", "KEY",
        "APIKEY", "PAT", "AUTH", "PRIVATE", "CERT", "SESSION", "SIGNATURE", "BEARER"}
# Segment suffixes, so MYTOKEN and DBPASS match but TOKENIZERS does not.
CRED_SUFFIX = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASS", "PWD", "APIKEY", "KEY",
               "CREDENTIAL", "CREDENTIALS")
PAIRS = {("API", "KEY"), ("ACCESS", "KEY"), ("SECRET", "KEY"), ("PRIVATE", "KEY"),
         ("REFRESH", "TOKEN"), ("ACCESS", "TOKEN"), ("CLIENT", "SECRET")}
SPLIT = re.compile(r"&&|\|\||\|&|;|\||&|\n")
WRAPPERS = {"env", "command", "nohup", "sudo", "doas", "time", "exec", "nice", "ionice",
            "stdbuf", "timeout", "builtin"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd"}
GROUPS = ("sandbox", "policy", "workspace", "provider")
MAX_DEPTH = 3

# Verbs that mutate durable state. sandbox update is included because it can
# change a sandbox policy; workspace create/delete because the guard only asks
# about deletion, so without this the approved action leaves no trace.
AUDITED = {
    "policy",
    "provider",
    "sandbox create", "sandbox delete", "sandbox update", "sandbox exec",
    "workspace create", "workspace delete", "workspace update",
}

# A bare `openshell` word (optionally .exe); openshell-admin, openshell.yaml do not count.
MENTION = re.compile(r"(?<![\w-])openshell(?:\.exe)?(?![\w-]|\.(?!exe\b)\w)")
ENCODED = re.compile(r"\b(pwsh|powershell)(\.exe)?\b[^\n]*\s[-/]e(c|nc|ncodedcommand)?\b", re.I)

INDIRECT_REASON = (
    "This command reaches openshell in a way the guard cannot evaluate (a substitution, "
    "subshell, eval, interpreter, pipe into a shell, or an unrecognised wrapper). Run the "
    "openshell command directly, or review it manually before allowing.")
EXPANSION_REASON = (
    "This openshell command uses shell expansion ($VAR, $(...), or backticks), so the "
    "guard cannot see the arguments that will actually run. Write the arguments out "
    "literally, or review it manually before allowing.")
ENCODED_REASON = (
    "This command runs an encoded PowerShell payload, which the guard cannot inspect. "
    "Review it manually before allowing.")
PARSE_ERROR_REASON = (
    "This command mentions openshell but could not be parsed (malformed payload, "
    "unbalanced quotes, or nesting too deep), so the guard could not evaluate it. "
    "Review it manually before allowing.")


def _variants(text):
    """Lower-cased views of the text with quoting removed: once with backslashes
    dropped (op\\enshell runs as openshell) and once with them read as path
    separators (C:\\tools\\openshell.exe)."""
    text = re.sub(r"[\"'^`]", "", text or "").lower()
    return text.replace("\\", ""), text.replace("\\", "/")


def mentions_openshell(text):
    """Quote-insensitive: op''enshell and "ope"nshell both count."""
    return any("openshell" in v for v in _variants(text))


def _mention_count(text):
    return max(len(MENTION.findall(v)) for v in _variants(text))


def _basename(token):
    name = re.split(r"[\\/]", token)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def segments(text):
    """Split a command on && || |& ; | & and newlines that sit outside quotes.

    Raises ValueError on unbalanced quotes.
    """
    parts, buf, quote, i = [], [], None, 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch == "\\" and i + 1 < len(text):
            buf.append(text[i:i + 2])
            i += 1
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        else:
            m = SPLIT.match(text, i)
            if m:
                parts.append("".join(buf))
                buf = []
                i = m.end()
                continue
            buf.append(ch)
        i += 1
    if quote:
        raise ValueError("unbalanced quotes")
    parts.append("".join(buf))
    return parts


def _shell_payload(argv):
    """Return the -c / /c payload of a shell invocation, or None."""
    for i, tok in enumerate(argv[1:], 1):
        low = tok.lower()
        if re.match(r"^-[a-z]*c[a-z]*$", low) or low in ("-command", "/c", "/k"):
            return argv[i + 1] if i + 1 < len(argv) else ""
    return None


def invocations(text, depth=0):
    """Yield (argv, raw_segment) for every openshell invocation inside a command.

    Raises ValueError on unbalanced quotes or nesting deeper than MAX_DEPTH.
    """
    if depth > MAX_DEPTH:
        raise ValueError("nesting too deep")
    for part in segments(text):
        part = part.strip()
        if not part:
            continue
        argv = shlex.split(part)
        while argv:
            head = argv[0]
            name = _basename(head)
            if not head.startswith("-") and "=" in head:
                argv = argv[1:]           # VAR=value prefix
            elif name in WRAPPERS:
                argv = argv[1:]
                while argv and (argv[0].startswith("-") or re.match(r"^\d+[smhd]?$", argv[0])):
                    argv = argv[1:]       # wrapper options, timeout durations
            elif name in SHELLS:
                payload = _shell_payload(argv)
                if payload:
                    yield from invocations(payload, depth + 1)
                argv = []
            else:
                break
        if argv and _basename(argv[0]) == "openshell":
            yield argv, part


def flags(argv):
    """Yield (name, value) for --flag=v, --flag v, -f=v and -f v."""
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("-"):
            if "=" in tok:
                name, value = tok.split("=", 1)
                yield name, value
            else:
                nxt = argv[i + 1] if i + 1 < len(argv) else ""
                if nxt and not nxt.startswith("-"):
                    yield tok, nxt
                    i += 1
                else:
                    yield tok, ""
        i += 1


def credential_like(name):
    segs = [s for s in re.split(r"[_\-]", name.upper()) if s]
    return (any(s in CRED or s.endswith(CRED_SUFFIX) for s in segs)
            or any(a in segs and b in segs for a, b in PAIRS))


def verb_of(args):
    """Return (verb, group). The group is found past any global flags and their
    values (`openshell --workspace acme sandbox delete`)."""
    positional = [a.lower() for a in args if not a.startswith("-")]
    for i, tok in enumerate(positional):
        if tok in GROUPS:
            nxt = positional[i + 1] if i + 1 < len(positional) else ""
            return (tok + " " + nxt).strip(), tok
    return " ".join(positional[:2]), (positional[0] if positional else "")


def _check(argv):
    args = argv[1:]
    verb, _ = verb_of(args)
    pairs = list(flags(args))
    names = {n for n, _ in pairs}

    # 1. Cross-workspace destruction: can empty a tenant never part of this mission.
    if verb == "sandbox delete" and ({"--all-workspaces", "--all"} & names):
        return DENY, ("Refusing a cross-workspace sandbox delete. Target one workspace "
                      "with --workspace, or delete by explicit name."), "cross-workspace-delete"

    # 2. Credential-shaped plain environment values. Segment-matched, so
    #    TOKENIZERS_PARALLELISM and PASSWORDLESS_LOGIN do not trip it.
    if verb in ("sandbox create", "sandbox update"):
        for name, value in pairs:
            if name in ("--env", "-e") and "=" in value:
                var = value.split("=", 1)[0]
                if credential_like(var):
                    return DENY, ("--env %s looks like a credential, and the sandboxed agent "
                                  "can read plain environment values directly. Attach it with "
                                  "--provider so the gateway injects it at the network "
                                  "boundary." % var), "credential-env"

    # 3. Global policy: while one exists, per-sandbox policy updates are rejected.
    if verb == "policy set" and "--global" in names:
        return ASK, ("This sets a platform-wide policy. While it is active, all sandbox-level "
                     "policy updates are rejected until it is deleted. Confirm this is a "
                     "deliberate baseline change."), "global-policy"

    # 4. Workspace deletion.
    if verb == "workspace delete":
        return ASK, ("Deleting a workspace removes its membership records and inference "
                     "routes. Confirm the workspace is empty and that this is intended."), \
            "workspace-delete"

    # 5. access: full on an endpoint.
    for name, value in pairs:
        if name == "--add-endpoint" and value.lower().endswith(":full"):
            return ASK, ("This grants access: full on an endpoint. Prefer read-only or "
                         "read-write plus explicit method/path rules. Confirm full access "
                         "is required."), "full-endpoint"
    return ALLOW, "", ""


def evaluate(command):
    """Return (decision, reason, rule) for a shell command; the most severe
    finding across every openshell call in it wins.

    `rule` names the check that fired ("" when allowed) so adapters can tell
    which asks their CLI's static permission rules are able to express.
    """
    command = command or ""
    if ENCODED.search(command):
        return ASK, ENCODED_REASON, "indirect"
    if not mentions_openshell(command):
        return ALLOW, "", ""
    try:
        calls = list(invocations(command))
    except ValueError:
        return ASK, PARSE_ERROR_REASON, "parse-error"

    best = (ALLOW, "", "")
    for argv, raw in calls:
        found = _check(argv)
        if found[0] == ALLOW and re.search(r"[$`]", raw):
            found = (ASK, EXPANSION_REASON, "expansion")
        if _RANK[found[0]] > _RANK[best[0]]:
            best = found
    if best[0] == DENY:
        return best
    # Every bare `openshell` word must belong to a parsed invocation.
    if best[0] == ALLOW and _mention_count(command) > len(calls):
        return ASK, INDIRECT_REASON, "indirect"
    return best


def plain_argv(command):
    """argv when the command is one bare `openshell ...` call with no quoting,
    operators, wrappers, expansion, or substitution; otherwise None.

    CLIs without an "ask" hook result fall back to static permission patterns.
    Those patterns only see the literal text, so an "ask" is passed to them only
    when the literal text is exactly what runs and the pattern really matches.
    """
    text = (command or "").strip()
    if not text or re.search(r"[\"'`$\\;&|<>()\n{}^%]", text):
        return None
    argv = text.split()
    return argv if argv[0] == "openshell" else None


def is_plain_invocation(command):
    return plain_argv(command) is not None


def _clean(text):
    return re.sub(r"[\t\r\n]", " ", text)


def audit_entries(command):
    """Return [(verb, argv-string)] for every state-mutating openshell call."""
    if not mentions_openshell(command):
        return []
    entries = []
    try:
        parts = segments(command)
    except ValueError:
        # Quote-blind fallback so the parseable calls are still recorded.
        parts = SPLIT.split(command)
    for part in parts:
        if not part.strip():
            continue
        try:
            calls = list(invocations(part))
        except ValueError:
            entries.append(("UNPARSED", _clean(part.strip())))
            continue
        for argv, _ in calls:
            verb, group = verb_of(argv[1:])
            if group in AUDITED or verb in AUDITED:
                entries.append((_clean(verb or group), _clean(" ".join(shlex.quote(a) for a in argv))))
    return entries
