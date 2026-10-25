"""Text transforms applied to every source file for one target."""

import re

_BLOCK = re.compile(
    r"^[ \t]*<!-- (only|not):([a-z0-9_,-]+) -->[ \t]*\n(.*?)^[ \t]*<!-- /\1 -->[ \t]*\n?",
    re.S | re.M)
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)(?::([a-z_]+))?\}\}")


def strip_conditionals(text, target):
    """Keep `<!-- only:a,b -->` blocks for listed targets and `<!-- not:a -->`
    blocks for every other target; drop the markers themselves."""
    def repl(m):
        kind, targets, inner = m.group(1), m.group(2).split(","), m.group(3)
        keep = (target in targets) if kind == "only" else (target not in targets)
        return inner if keep else ""
    prev = None
    while prev != text:  # nested blocks
        prev, text = text, _BLOCK.sub(repl, text)
    if re.search(r"<!-- /?(only|not)[:\s]", text):
        raise ValueError("unbalanced conditional block")
    return text


def fill(text, values, where="?"):
    """Replace {{name}} and {{tool:key}} placeholders; unknown ones are errors."""
    def repl(m):
        key = m.group(1) if m.group(2) is None else "%s:%s" % (m.group(1), m.group(2))
        if key not in values:
            raise KeyError("unknown placeholder {{%s}} in %s" % (key, where))
        return values[key]
    return _PLACEHOLDER.sub(repl, text)


def placeholders(text):
    return {m.group(0) for m in _PLACEHOLDER.finditer(text)}
