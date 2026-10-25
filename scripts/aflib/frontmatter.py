"""Markdown frontmatter: a small, strict YAML subset (stdlib only).

Supported: block mappings nested by indentation, block lists (`- item`),
inline lists (`[a, b]`), and scalars (plain, "double", 'single', true/false,
integers). Anything else raises ValueError so the build fails loudly instead
of mis-reading a source file.
"""

import json
import re

_INT = re.compile(r"^-?\d+$")
_PLAIN_SAFE = re.compile(r"^[^\s\"'`{}\[\],&*#?|<>=!%@-][^#]*$")


def split(text):
    """Return (meta, body). Text without frontmatter yields ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 3)
    if end == -1:
        if text.endswith("\n---"):
            end = len(text) - 4
        else:
            raise ValueError("unterminated frontmatter")
    return parse(text[4:end]), text[end + 5:]


def join(meta, body):
    return "---\n" + dump(meta) + "---\n" + body


def _scalar(raw):
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == '"':
        return json.loads(raw)
    if raw[0] == "'":
        if not raw.endswith("'") or len(raw) < 2:
            raise ValueError("bad single-quoted scalar: %r" % raw)
        return raw[1:-1].replace("''", "'")
    if raw[0] == "[":
        if not raw.endswith("]"):
            raise ValueError("bad inline list: %r" % raw)
        inner = raw[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    if raw in ("true", "false"):
        return raw == "true"
    if _INT.match(raw):
        return int(raw)
    return raw


def parse(text):
    lines = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in text.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    value, pos = _block(lines, 0, 0)
    if pos != len(lines):
        raise ValueError("unexpected indentation near %r" % lines[pos][1])
    return value if value is not None else {}


def _block(lines, pos, indent):
    if pos >= len(lines) or lines[pos][0] < indent:
        return None, pos
    indent = lines[pos][0]
    if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
        out = []
        while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("-"):
            out.append(_scalar(lines[pos][1][1:]))
            pos += 1
        return out, pos
    out = {}
    while pos < len(lines) and lines[pos][0] == indent:
        line = lines[pos][1]
        m = re.match(r'^("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^:]+?)\s*:(?:\s+(.*))?$', line)
        if not m:
            raise ValueError("expected 'key: value', got %r" % line)
        key = _scalar(m.group(1)) if m.group(1)[0] in "\"'" else m.group(1)
        pos += 1
        if m.group(2) is None or m.group(2) == "":
            child, pos = _block(lines, pos, indent + 1)
            out[key] = child if child is not None else ""
        else:
            out[key] = _scalar(m.group(2))
    return out, pos


def _fmt(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    s = str(value)
    if (s and _PLAIN_SAFE.match(s) and ": " not in s and not s.endswith(":")
            and s not in ("true", "false") and not _INT.match(s) and s == s.strip()):
        return s
    return json.dumps(s, ensure_ascii=False)


def _key(key):
    return key if re.match(r"^[A-Za-z0-9_.-]+$", key) else json.dumps(key)


def dump(meta, indent=0):
    out = []
    pad = " " * indent
    for key, value in meta.items():
        if isinstance(value, dict):
            out.append("%s%s:\n" % (pad, _key(key)))
            out.append(dump(value, indent + 2))
        else:
            out.append("%s%s: %s\n" % (pad, _key(key), _fmt(value)))
    return "".join(out)
