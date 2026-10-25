"""Mission dashboard: render_dashboard.py (metrics + render) and the page it writes.

Stdlib only, Python 3.9+. The renderer runs as a subprocess with sys.executable, the way the
report flow runs it. Set REPORT_RENDERER to the path of another render_dashboard.py to run the
suite against a copy (this is how the tests are proven to fail against a deliberately broken
renderer). All fixtures under tests/report/fixtures/ are synthetic.
"""

import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(ROOT, "tests", "report", "fixtures")
SRC_SCRIPTS = os.path.join(ROOT, "src", "skills", "mission-report", "scripts")
DEFAULT_RENDERER = os.path.join(SRC_SCRIPTS, "render_dashboard.py")
RENDERER = os.environ.get("REPORT_RENDERER") or DEFAULT_RENDERER

SLUG = "synthetic-dashboard-fixture"
HOSTILE_SLUG = "hostile-slug"
GENERATED = "2026-01-05T09:20:00Z"
NOT_RECORDED = "Not recorded"
BG = "#0a0c10"
PAGE_BUDGET = 150 * 1024
HOSTILE_LEVEL = "L4\"><script>alert(9)</script>'onmouseover=alert(9) x='"

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
ALLOWED_TAGS = frozenset(
    "html head meta title style body div header h1 h2 h3 dl dt dd main section ul ol li p span time "
    "details summary article svg circle rect line text strong code button script footer".split())
URL_ATTRS = frozenset(
    "src href srcset action poster formaction data cite ping background longdesc manifest codebase "
    "archive profile icon xlink:href data-src data-href data-url data-srcset".split())

WORK = None
_PAGES = {}


def fx(name):
    return os.path.join(FIXTURES, name)


def load_fixture(name):
    with open(fx(name), encoding="utf-8") as fh:
        return json.load(fh)


def run_cli(args, cwd=None, renderer=None, timeout=180):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, renderer or RENDERER] + list(args), cwd=cwd or WORK, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    proc.out = proc.stdout.decode("utf-8", "replace")
    proc.err = proc.stderr.decode("utf-8", "replace")
    return proc


def setUpModule():
    global WORK
    WORK = tempfile.mkdtemp(prefix="dash-test-")


def tearDownModule():
    shutil.rmtree(WORK, ignore_errors=True)


def render_args(report, out, registry=None, metrics=None, slug=SLUG, level="L4", generated=GENERATED):
    args = ["render", "--report", report, "--mission", slug, "--out", out]
    if registry:
        args += ["--registry", registry]
    if metrics:
        args += ["--metrics", metrics]
    if level:
        args += ["--operator-level", level]
    if generated:
        args += ["--generated-at", generated]
    return args


def read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8")


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


class Page(HTMLParser):
    """Parse a page into elements, text, scripts and styles; collect structural errors."""

    def __init__(self, source):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.source = source
        self.stack = []
        self.elems = []
        self.errors = []
        self.scripts = []
        self.styles = []
        self.doctype = None
        self.svg_depth = 0
        self.pieces = []
        self.feed(source)
        self.close()
        for rec in self.stack:
            self.errors.append("unclosed <%s>" % rec["tag"])

    def _open(self, tag, attrs):
        names = [name for name, _ in attrs]
        for name in set(names):
            if names.count(name) > 1:
                self.errors.append("duplicate attribute %s on <%s>" % (name, tag))
        rec = {"tag": tag, "attrs": dict(attrs), "attr_names": names, "text": [], "kids": [],
               "parent": self.stack[-1] if self.stack else None, "svg": self.svg_depth > 0 or tag == "svg"}
        rec["classes"] = (rec["attrs"].get("class") or "").split()
        if rec["parent"] is not None:
            rec["parent"]["kids"].append(rec)
        self.elems.append(rec)
        return rec

    def handle_decl(self, decl):
        self.doctype = decl

    def handle_starttag(self, tag, attrs):
        rec = self._open(tag, attrs)
        if tag in VOID:
            return
        self.stack.append(rec)
        if tag == "svg":
            self.svg_depth += 1

    def handle_startendtag(self, tag, attrs):
        rec = self._open(tag, attrs)
        if tag not in VOID and not rec["svg"]:
            self.errors.append("self-closing non-void <%s/> outside svg" % tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            self.errors.append("end tag for void element </%s>" % tag)
            return
        if self.stack and self.stack[-1]["tag"] == tag:
            if tag == "svg":
                self.svg_depth -= 1
            self.stack.pop()
        else:
            top = self.stack[-1]["tag"] if self.stack else None
            self.errors.append("unbalanced </%s> (open: %s)" % (tag, top))

    def handle_data(self, data):
        top = self.stack[-1]["tag"] if self.stack else None
        if top == "script":
            self.scripts.append(data)
            return
        if top == "style":
            self.styles.append(data)
            return
        self.pieces.append(data)
        for rec in self.stack:
            rec["text"].append(data)

    def find(self, tag=None, cls=None):
        return [r for r in self.elems if (tag is None or r["tag"] == tag) and (cls is None or cls in r["classes"])]

    @staticmethod
    def text_of(rec):
        return " ".join("".join(rec["text"]).split())

    @property
    def text(self):
        return " ".join("".join(self.pieces).split())

    @property
    def css(self):
        return "".join(self.styles)

    @property
    def js(self):
        return "".join(self.scripts)

    def tags(self):
        return set(r["tag"] for r in self.elems)

    def meta(self, **want):
        for rec in self.find("meta"):
            if all((rec["attrs"].get(k.replace("_", "-")) or "").lower() == v.lower() for k, v in want.items()):
                return rec
        return None


def page_of(name):
    """Render each named variant once and cache the parsed page."""
    if name in _PAGES:
        return _PAGES[name]
    out = os.path.join(WORK, name + ".html")
    report, registry, metrics = fx("synthetic-mission-report.jsonld"), fx("synthetic-registry.json"), fx("synthetic-metrics.json")
    level, slug = "L4", SLUG
    if name == "auto":
        registry = fx("synthetic-registry-autonomous.json")
    elif name == "retried":
        data = load_fixture("synthetic-registry.json")
        data["actions"][1]["runs"][0]["first_attempt"] = False
        registry = write_json(os.path.join(WORK, "retried-registry.json"), data)
    elif name == "bare":
        registry, metrics, level = None, None, None
    elif name in ("hostile", "hostile_level"):
        report, registry, metrics = (fx("synthetic-hostile-report.jsonld"), fx("synthetic-hostile-registry.json"),
                                     fx("synthetic-hostile-metrics.json"))
        slug = HOSTILE_SLUG
        if name == "hostile_level":
            level = HOSTILE_LEVEL
    elif name == "injection":
        report, metrics = fx("synthetic-injection-report.jsonld"), fx("synthetic-injection-metrics.json")
    proc = run_cli(render_args(report, out, registry, metrics, slug, level))
    if proc.returncode != 0:
        raise AssertionError("render %s failed (%s): %s" % (name, proc.returncode, proc.err))
    page = Page(read_text(out))
    page.name = name
    _PAGES[name] = page
    return page


CLEAN_PAGES = ("normal", "auto", "retried", "bare")
HOSTILE_PAGES = ("hostile", "hostile_level")
ALL_PAGES = CLEAN_PAGES + HOSTILE_PAGES + ("injection",)


# ------------------------------------------------------------------------------ CSS helpers

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse_css(css, media=()):
    """Flat list of (prelude, [(prop, value)], media chain); nested at-rules are flattened."""
    css = strip_comments(css)
    rules, i, n = [], 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        prelude = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if prelude.startswith("@") and "{" in body:
            rules.extend(parse_css(body, media + (prelude,)))
        else:
            decls = []
            for part in body.split(";"):
                if ":" in part:
                    prop, value = part.split(":", 1)
                    decls.append((prop.strip().lower(), " ".join(value.split())))
            rules.append((prelude, decls, media))
        i = k
    return rules


def root_tokens(css):
    tokens = {}
    for prelude, decls, _ in parse_css(css):
        if prelude == ":root":
            for prop, value in decls:
                if prop.startswith("--"):
                    tokens.setdefault(prop, value)
    return tokens


def outside_root(css):
    return [r for r in parse_css(css) if r[0] != ":root"]


COLOR_PROPS = frozenset(
    "color background background-color border border-top border-right border-bottom border-left border-color "
    "border-top-color border-right-color border-bottom-color border-left-color outline outline-color fill stroke "
    "caret-color box-shadow text-shadow scrollbar-color accent-color text-decoration-color column-rule "
    "stop-color flood-color lighting-color".split())
NAMED_COLORS = frozenset(
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown "
    "burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan "
    "darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid "
    "darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet "
    "deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro "
    "ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki "
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow "
    "lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray "
    "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine "
    "mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise "
    "mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab "
    "orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru "
    "pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown "
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan "
    "teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen".split())
COLOR_FUNC = re.compile(r"(?:#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color|color-mix)\()")


def luminance(value):
    value = value.strip().lstrip("#")

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [lin(int(value[i:i + 2], 16) / 255.0) for i in (0, 2, 4)]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def sha_token(text):
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def csp_of(page):
    rec = page.meta(http_equiv="content-security-policy")
    if rec is None:
        return None
    policy = {}
    for part in rec["attrs"].get("content", "").split(";"):
        bits = part.split()
        if bits:
            policy[bits[0].lower()] = bits[1:]
    return policy


def kpi_map(page):
    """label -> (figure text, sub text)"""
    out = {}
    for card in page.find("div", "kpi"):
        definition = [k for k in card["kids"] if k["tag"] == "dl"][0]
        label = Page.text_of([k for k in definition["kids"] if k["tag"] == "dt"][0])
        figure = [k for k in definition["kids"] if k["tag"] == "dd"][0]
        sub = [k for k in card["kids"] if k["tag"] == "p"]
        out[label] = (Page.text_of(figure), Page.text_of(sub[0]) if sub else "")
    return out


def gate_items(page):
    return [li for li in page.find("li") if li["parent"]["classes"] == ["gate-list"]]

# ============================================================================ 1. zero network

class ZeroNetwork(unittest.TestCase):
    def test_no_url_bearing_attribute_anywhere(self):
        for name in ALL_PAGES:
            for rec in page_of(name).elems:
                for attr, value in rec["attrs"].items():
                    if attr not in URL_ATTRS:
                        continue
                    self.fail("%s: <%s %s=%r> is a URL-bearing attribute" % (name, rec["tag"], attr, value))

    def test_no_attribute_value_is_a_remote_url(self):
        pattern = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//|https?://|\burl\(", re.I)
        for name in CLEAN_PAGES:
            for rec in page_of(name).elems:
                for attr, value in rec["attrs"].items():
                    self.assertFalse(value and pattern.search(value),
                                     "%s: <%s %s=%r> looks like a remote URL" % (name, rec["tag"], attr, value))

    def test_no_network_capable_elements(self):
        banned = set("link iframe frame frameset object embed applet base form input audio video source track "
                     "picture image use foreignobject".split())
        for name in ALL_PAGES:
            page = page_of(name)
            self.assertEqual(banned & page.tags(), set(), name)
            for rec in page.find("script"):
                self.assertNotIn("src", rec["attrs"], name)
            self.assertEqual(page.find("img"), [], name)
            self.assertIsNone(page.meta(http_equiv="refresh"), name)

    def test_no_http_reference_anywhere_in_the_clean_pages(self):
        for name in CLEAN_PAGES:
            page = page_of(name)
            self.assertNotRegex(page.source, r"(?i)https?:", name)
            self.assertNotRegex(page.css + page.js, r"(?i)(?:https?:)?//[a-z0-9-]+(?:\.[a-z0-9-]+)+", name)

    def test_css_has_no_import_url_or_font_loading(self):
        for name in ALL_PAGES:
            css = strip_comments(page_of(name).css).lower()
            for needle in ("@import", "url(", "image-set(", "@font-face", "expression("):
                self.assertNotIn(needle, css, "%s: %s" % (name, needle))
            self.assertNotRegex(css, r"\bsrc\s*:", name)

    def test_script_uses_no_network_or_dynamic_code_api(self):
        banned = (r"\bfetch\b", r"XMLHttpRequest", r"\bWebSocket\b", r"\bEventSource\b", r"sendBeacon",
                  r"importScripts", r"\bimport\s*\(", r"\bimport\s+[\w{*]", r"\bWorker\b", r"serviceWorker",
                  r"\beval\b", r"\bFunction\b", r"innerHTML", r"outerHTML", r"insertAdjacentHTML",
                  r"document\.write", r"window\.open", r"\blocation\b", r"\.src\s*=", r"\.href\s*=",
                  r"setTimeout\s*\(\s*[\"']", r"setInterval\s*\(\s*[\"']")
        for name in ALL_PAGES:
            js = page_of(name).js
            self.assertTrue(js.strip(), "inline script is missing")
            for pattern in banned:
                self.assertNotRegex(js, pattern, "%s: %s" % (name, pattern))

    def test_csp_meta_is_present_and_precedes_style_and_script(self):
        for name in ALL_PAGES:
            page = page_of(name)
            self.assertIsNotNone(csp_of(page), name + ": Content-Security-Policy meta tag missing")
            index = [i for i, r in enumerate(page.elems)
                     if r["tag"] == "meta" and (r["attrs"].get("http-equiv") or "").lower() == "content-security-policy"]
            self.assertEqual(len(index), 1, name)
            order = [r["tag"] for r in page.elems]
            self.assertLess(index[0], min(order.index("style"), order.index("script")), name)

    def test_csp_default_none_and_no_unsafe_sources(self):
        for name in ALL_PAGES:
            policy = csp_of(page_of(name))
            self.assertIsNotNone(policy, name)
            self.assertEqual(policy.get("default-src"), ["'none'"], name)
            for directive, sources in policy.items():
                for source in sources:
                    label = "%s %s %s" % (name, directive, source)
                    self.assertNotIn(source.lower(), ("'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'", "*",
                                                      "https:", "http:", "blob:", "'self'", "'strict-dynamic'"), label)
                    self.assertNotRegex(source, r"(?i)^(?:https?:)?//|^[a-z]+://", label)
                    self.assertNotEqual(source.lower(), "data:", label)

    def test_csp_connect_and_other_fetch_directives_stay_blocked(self):
        for name in ALL_PAGES:
            policy = csp_of(page_of(name))
            self.assertIsNotNone(policy, name)
            for directive in ("connect-src", "frame-src", "child-src", "object-src", "font-src", "media-src",
                              "worker-src", "manifest-src", "prefetch-src"):
                self.assertEqual(policy.get(directive, ["'none'"]), ["'none'"], "%s %s" % (name, directive))
            # default-src 'none' already blocks images; img-src may only repeat that
            self.assertLessEqual(set(policy.get("img-src", ["'none'"])), set(["'none'"]), name)
            self.assertEqual(policy.get("base-uri"), ["'none'"], name)
            self.assertEqual(policy.get("form-action"), ["'none'"], name)

    def test_csp_hashes_match_the_inline_script_and_style(self):
        for name in ALL_PAGES:
            page = page_of(name)
            policy = csp_of(page)
            self.assertIsNotNone(policy, name)
            self.assertEqual(len(page.find("script")), 1, name)
            self.assertEqual(len(page.find("style")), 1, name)
            self.assertEqual(policy.get("style-src"), [sha_token(page.css.replace("\r\n", "\n"))], name)
            self.assertEqual(policy.get("script-src"), [sha_token(page.js.replace("\r\n", "\n"))], name)

    def test_no_inline_event_handlers_style_attributes_or_xmlns(self):
        for name in ALL_PAGES:
            for rec in page_of(name).elems:
                for attr in rec["attr_names"]:
                    self.assertFalse(attr.startswith("on"), "%s: <%s %s>" % (name, rec["tag"], attr))
                    self.assertNotIn(attr, ("style", "xmlns"), "%s: <%s %s>" % (name, rec["tag"], attr))


# ============================================================================ 2. HTML validity

class HtmlValidity(unittest.TestCase):
    def test_document_prolog(self):
        for name in ALL_PAGES:
            page = page_of(name)
            self.assertEqual((page.doctype or "").lower(), "doctype html", name)
            self.assertTrue(page.source.lstrip().lower().startswith("<!doctype html>"), name)
            root = page.find("html")
            self.assertEqual(len(root), 1, name)
            self.assertRegex(root[0]["attrs"].get("lang") or "", r"^[A-Za-z]{2,3}(-[A-Za-z0-9]+)*$", name)
            metas = page.find("meta")
            self.assertEqual(metas[0]["attrs"].get("charset", "").lower(), "utf-8", name)
            self.assertLess(page.source.lower().index("charset"), 1024, name)
            viewport = [m for m in metas if m["attrs"].get("name") == "viewport"]
            self.assertEqual(len(viewport), 1, name)
            self.assertIn("width=device-width", viewport[0]["attrs"].get("content", ""), name)
            titles = page.find("title")
            self.assertEqual(len(titles), 1, name)
            self.assertTrue(Page.text_of(titles[0]), name)

    def test_exactly_one_h1_and_heading_levels_do_not_skip(self):
        for name in ALL_PAGES:
            page = page_of(name)
            self.assertEqual(len(page.find("h1")), 1, name)
            self.assertTrue(Page.text_of(page.find("h1")[0]), name)
            levels = [int(r["tag"][1]) for r in page.elems if r["tag"] in ("h1", "h2", "h3")]
            self.assertEqual(levels[0], 1, name)
            for prev, cur in zip(levels, levels[1:]):
                self.assertLessEqual(cur, prev + 1, "%s: heading levels skip" % name)

    def test_tags_are_balanced_and_only_known_tags_appear(self):
        for name in ALL_PAGES:
            page = page_of(name)
            self.assertEqual(page.errors, [], name)
            self.assertEqual(page.stack, [], name)
            self.assertLessEqual(page.tags(), ALLOWED_TAGS,
                                 "%s: unexpected tags %s" % (name, sorted(page.tags() - ALLOWED_TAGS)))

    def test_ids_are_unique(self):
        for name in ALL_PAGES:
            ids = [r["attrs"]["id"] for r in page_of(name).elems if r["attrs"].get("id") is not None]
            self.assertTrue(ids, name)
            self.assertEqual(len(ids), len(set(ids)),
                             "%s: duplicate ids %s" % (name, sorted(set(i for i in ids if ids.count(i) > 1))))
            for value in ids:
                self.assertRegex(value, r"^\S+$", name)

    def test_reference_attributes_point_at_existing_ids(self):
        for name in ALL_PAGES:
            page = page_of(name)
            ids = set(r["attrs"].get("id") for r in page.elems)
            referenced = 0
            for rec in page.elems:
                for attr in ("aria-controls", "aria-labelledby", "aria-describedby", "for", "aria-owns"):
                    value = rec["attrs"].get(attr)
                    if value is None:
                        continue
                    self.assertTrue(value.split(), "%s: empty %s" % (name, attr))
                    for target in value.split():
                        referenced += 1
                        self.assertIn(target, ids, "%s: <%s %s=%s> has no target" % (name, rec["tag"], attr, target))
            self.assertGreater(referenced, 0, name)

    def test_every_inline_svg_has_a_role_and_an_accessible_name(self):
        for name in ALL_PAGES:
            svgs = page_of(name).find("svg")
            self.assertGreater(len(svgs), 0, name)
            for rec in svgs:
                if rec["attrs"].get("aria-hidden") == "true":
                    continue
                self.assertIn(rec["attrs"].get("role"), ("img", "graphics-document"), name)
                titled = any(k["tag"] == "title" for k in rec["kids"])
                self.assertTrue((rec["attrs"].get("aria-label") or "").strip() or titled,
                                "%s: <svg class=%s> has no accessible name" % (name, rec["classes"]))

    def test_links_buttons_and_details_are_well_formed(self):
        for name in ALL_PAGES:
            page = page_of(name)
            for rec in page.elems:
                for attr in ("href", "src"):
                    if attr in rec["attrs"]:
                        self.assertTrue((rec["attrs"][attr] or "").strip(), "%s: empty %s" % (name, attr))
            for rec in page.find("button"):
                self.assertEqual(rec["attrs"].get("type"), "button", name)
                self.assertTrue(rec["attrs"].get("aria-label") or Page.text_of(rec), name)
            for rec in page.find("details"):
                self.assertEqual(rec["kids"][0]["tag"], "summary", "%s: <details> must start with <summary>" % name)

    def test_dt_and_dd_live_in_a_dl(self):
        for name in ALL_PAGES:
            page = page_of(name)
            for rec in page.find("dt") + page.find("dd"):
                parent = rec["parent"]
                if parent["tag"] == "div":
                    parent = parent["parent"]
                self.assertEqual(parent["tag"], "dl", name)


# ============================================================================ 3. escaping

HOSTILE_PAYLOADS = ('"><script>alert(1)</script>', "'onmouseover=alert(2) x='", "</style><script>alert(3)</script>",
                    "</script><script>alert(4)</script>", "<img src=x onerror=alert(5)>", "alert(9)</script>")
KNOWN_ATTRS = frozenset(
    "charset name content http-equiv lang class id role aria-label aria-labelledby aria-hidden datetime viewbox "
    "preserveaspectratio cx cy r x y x1 x2 y1 y2 width height transform stroke-dasharray stroke-dashoffset type "
    "data-path hidden".split())


class Escaping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = page_of("hostile")
        cls.level_page = page_of("hostile_level")
        cls.metrics = load_fixture("synthetic-hostile-metrics.json")
        cls.report = load_fixture("synthetic-hostile-report.jsonld")

    def pages(self):
        return (self.page, self.level_page)

    def test_payloads_never_appear_raw(self):
        for page in self.pages():
            for payload in HOSTILE_PAYLOADS:
                self.assertNotIn(payload, page.source, "%s: %s" % (page.name, payload))
            for fragment in ("<img", "<b>", '"><script', "'onmouseover", "<script>alert", "</script><script>",
                             "</style><script>", "onerror=alert(5)>"):
                self.assertNotIn(fragment, page.source, "%s: %s" % (page.name, fragment))

    def test_exactly_one_script_and_one_style_element(self):
        for page in self.pages():
            self.assertEqual(len(page.find("script")), 1, page.name)
            self.assertEqual(len(page.find("style")), 1, page.name)
            self.assertEqual(page.source.count("<script"), 1, page.name)
            self.assertEqual(page.source.count("</script>"), 1, page.name)
            self.assertEqual(page.source.count("<style"), 1, page.name)
            self.assertEqual(page.source.count("</style>"), 1, page.name)

    def test_no_injected_elements_or_attributes(self):
        for page in self.pages():
            self.assertLessEqual(page.tags(), ALLOWED_TAGS, page.name)
            self.assertEqual(page.errors, [], page.name)
            for rec in page.elems:
                for attr in rec["attr_names"]:
                    self.assertFalse(attr.startswith("on"), "%s: %s" % (page.name, attr))
                self.assertLessEqual(set(rec["attr_names"]), KNOWN_ATTRS, "%s: <%s %s>" % (page.name, rec["tag"], rec["attr_names"]))

    def test_data_path_round_trips_to_the_exact_original_string(self):
        expected = set(f["path"] for f in self.metrics["files"])
        self.assertEqual(len(expected), 8)
        for page in self.pages():
            buttons = page.find("button")
            self.assertEqual(set(b["attrs"]["data-path"] for b in buttons), expected, page.name)
            shown = set(Page.text_of(c) for c in page.find("code", "fpath"))
            self.assertEqual(shown, set(" ".join(p.split()) for p in expected), page.name)
            for button in buttons:
                self.assertEqual(button["attrs"]["aria-label"], "Copy path " + button["attrs"]["data-path"])

    def test_hostile_text_is_displayed_as_text_not_dropped(self):
        graph = self.report["@graph"]
        title = " ".join(graph[0]["name"].split())
        self.assertEqual(Page.text_of(self.page.find("h1")[0]), title)
        self.assertEqual(Page.text_of(self.page.find("title")[0]), "Mission report: " + title)
        self.assertIn(HOSTILE_SLUG, self.page.meta(name="description")["attrs"]["content"])
        for node in graph[1:]:
            self.assertIn(" ".join(node["name"].split()), self.page.text)
        self.assertIn(HOSTILE_PAYLOADS[1], self.page.text)
        self.assertIn(HOSTILE_PAYLOADS[4], self.page.text)

    def test_operator_level_slug_and_metrics_values_are_escaped(self):
        values = [Page.text_of(r) for r in self.level_page.find(None, "mono")]
        self.assertIn(HOSTILE_LEVEL, values)
        self.assertIn(HOSTILE_SLUG, values)
        self.assertNotIn(HOSTILE_LEVEL, self.level_page.source)
        suite = self.metrics["tests"][0]
        names = [Page.text_of(r) for r in self.page.find("strong")]
        self.assertIn(" ".join(suite["name"].split()), names)
        self.assertIn(suite["command"], [Page.text_of(r) for r in self.page.find("code")])

    def test_registry_action_name_is_escaped(self):
        name = load_fixture("synthetic-hostile-registry.json")["actions"][0]["name"]
        self.assertIn(" ".join(name.split()), self.page.text)
        self.assertIn(html.escape(name, quote=True), self.page.source)

    def test_escaped_forms_are_what_the_source_contains(self):
        self.assertIn(html.escape(HOSTILE_PAYLOADS[0], quote=True), self.page.source)
        self.assertIn("&quot;&gt;&lt;script&gt;", self.page.source)
        self.assertIn("&#x27;onmouseover=", self.page.source)

# ============================================================================ 4. Hallmark floor

class HallmarkFloor(unittest.TestCase):
    def test_every_literal_colour_sits_in_the_root_token_block(self):
        for name in ALL_PAGES:
            rules = outside_root(page_of(name).css)
            self.assertGreater(len(rules), 20, name)
            for prelude, decls, _ in rules:
                for prop, value in decls:
                    self.assertFalse(prop.startswith("--"), "%s: %s declared outside :root in %r" % (name, prop, prelude))
                    if prop not in COLOR_PROPS:
                        continue
                    bare = re.sub(r"var\([^)]*\)", "", value)
                    self.assertIsNone(COLOR_FUNC.search(bare), "%s: literal colour in %s { %s: %s }" % (name, prelude, prop, value))
                    self.assertEqual(set(re.findall(r"[a-z]+", bare.lower())) & NAMED_COLORS, set(),
                                     "%s: named colour in %s { %s: %s }" % (name, prelude, prop, value))

    def test_markup_carries_no_literal_colour_or_font(self):
        for name in ALL_PAGES:
            for rec in page_of(name).elems:
                for attr in ("fill", "stroke", "stop-color", "color", "font-family", "style", "bgcolor"):
                    self.assertNotIn(attr, rec["attrs"], "%s: <%s %s>" % (name, rec["tag"], attr))

    def test_font_family_is_declared_only_as_a_token(self):
        for name in ALL_PAGES:
            css = page_of(name).css
            for prelude, decls, _ in outside_root(css):
                for prop, value in decls:
                    if prop == "font-family":
                        self.assertRegex(value, r"^var\(--[a-z-]+\)$", "%s: %s { font-family: %s }" % (name, prelude, value))
                    if prop == "font":
                        self.assertNotRegex(re.sub(r"var\([^)]*\)", "", value), r"[A-Za-z]{3,}\s*(,|$)", name)
            tokens = root_tokens(css)
            self.assertTrue(re.sub(r"\s", "", tokens.get("--font-mono", "")).startswith('"GeistMono","JetBrainsMono",ui-monospace'),
                            tokens.get("--font-mono"))
            self.assertTrue(tokens.get("--font-ui", "").startswith("Inter, system-ui"), tokens.get("--font-ui"))

    def test_no_font_files_are_embedded_or_loaded(self):
        for name in ALL_PAGES:
            page = page_of(name)
            css = strip_comments(page.css).lower()
            self.assertNotIn("@font-face", css, name)
            self.assertNotIn("font-display", css, name)
            self.assertNotIn("base64", page.source.lower(), name)

    def test_no_transition_all_and_no_animation_of_layout_properties(self):
        layout = re.compile(r"\b(width|height|top|left|right|bottom|inset|margin|padding)\b")
        for name in ALL_PAGES:
            css = strip_comments(page_of(name).css)
            self.assertNotRegex(css, r"transition(?:-property)?\s*:[^;}]*\ball\b", name)
            seen = 0
            for prelude, decls, media in parse_css(css):
                in_keyframes = prelude.startswith("@keyframes") or any(m.startswith("@keyframes") for m in media)
                for prop, value in decls:
                    if prop in ("transition", "transition-property", "will-change"):
                        seen += 1
                        self.assertIsNone(layout.search(value), "%s: %s { %s: %s }" % (name, prelude, prop, value))
                    if prop.startswith("animation"):
                        self.assertIsNone(layout.search(value), name)
                    if in_keyframes:
                        self.assertNotIn(prop, ("width", "height", "top", "left"), name)
            self.assertGreater(seen, 0, name + ": expected at least one declared transition to check")

    def test_overflow_x_is_clip_on_html_and_body(self):
        for name in ALL_PAGES:
            css = page_of(name).css
            rules = parse_css(css)
            for selector in ("html", "body"):
                hits = [d for p, d, m in rules if selector in [s.strip() for s in p.split(",")] and not m]
                self.assertTrue(hits, "%s: no %s rule" % (name, selector))
                props = dict(item for decls in hits for item in decls)
                self.assertEqual(props.get("overflow-x"), "clip", "%s: %s overflow-x" % (name, selector))
                self.assertNotIn(props.get("overflow"), ("hidden", "scroll", "auto"), name)
            self.assertNotRegex(strip_comments(css), r"100vw", name)
            self.assertNotRegex(strip_comments(css), r"overflow-x\s*:\s*hidden", name)

    def test_focus_visible_rule_exists_and_appears_instantly(self):
        for name in ALL_PAGES:
            focus = [r for r in parse_css(page_of(name).css) if ":focus-visible" in r[0]]
            self.assertTrue(focus, name + ": no :focus-visible rule")
            for _, decls, _ in focus:
                self.assertTrue(any(p in ("outline", "outline-color", "box-shadow") for p, _ in decls), name)
                self.assertFalse(any(p.startswith("transition") for p, _ in decls), name)

    def test_prefers_reduced_motion_rule_covers_every_transition(self):
        for name in ALL_PAGES:
            rules = parse_css(page_of(name).css)
            reduced = [r for r in rules if any("prefers-reduced-motion" in m and "reduce" in m for m in r[2])]
            self.assertTrue(reduced, name + ": no prefers-reduced-motion: reduce rule")
            declared = [p for _, d, m in rules if m == () for p, _ in d if p.startswith("transition") or p.startswith("animation")]
            if declared:
                values = [v for _, d, _ in reduced for p, v in d if p in ("transition", "animation")]
                self.assertTrue(any("none" in v for v in values), name)

    def test_no_tracked_capitals_small_caps_or_gradients(self):
        for name in ALL_PAGES:
            page = page_of(name)
            for prelude, decls, _ in parse_css(page.css):
                props = dict(decls)
                self.assertNotEqual(props.get("text-transform"), "uppercase", "%s: %s" % (name, prelude))
                for prop, value in decls:
                    self.assertNotRegex(value, r"small-caps", "%s %s" % (name, prelude))
                    self.assertNotIn("gradient", value.lower(), "%s %s { %s }" % (name, prelude, prop))
            self.assertNotIn("gradient", page.source.lower(), name)

    def test_no_emoji_arrows_dashes_or_middle_dots_in_the_rendered_page(self):
        emoji = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF\uFE0F\u200D\u2900-\u297F]")
        dashes = re.compile("[\u2012\u2013\u2014\u2015\u2212]")
        dots = re.compile("[\u00B7\u2022\u2219\u22C5\u25CF\u25CB]")
        for name in CLEAN_PAGES + HOSTILE_PAGES:
            page = page_of(name)
            self.assertIsNone(emoji.search(page.source), "%s: emoji or arrow %r" % (name, emoji.search(page.source)))
            self.assertIsNone(dashes.search(page.source), "%s: em or en dash %r" % (name, dashes.search(page.source)))
            visible = page.text + " " + " ".join(v for r in page.elems for v in r["attrs"].values() if v)
            self.assertIsNone(dots.search(visible), "%s: middle dot or bullet in rendered text" % name)
            self.assertNotRegex(page.text, r"\s[|/]\s", name + ": delimiter-joined meta string")

    def test_no_card_inside_a_card(self):
        for name in ALL_PAGES:
            cards = page_of(name).find(None, "card")
            self.assertGreater(len(cards), 5, name)
            for rec in cards:
                parent = rec["parent"]
                while parent is not None:
                    self.assertNotIn("card", parent["classes"], "%s: card inside card (%s)" % (name, rec["classes"]))
                    parent = parent["parent"]

    def test_first_css_line_is_the_hallmark_stamp(self):
        for name in ALL_PAGES:
            lines = [ln for ln in page_of(name).css.split("\n") if ln.strip()]
            self.assertTrue(lines[0].strip().startswith("/* Hallmark"), "%s: first CSS line %r" % (name, lines[0][:60]))
            for field in ("shape:", "genre:", "theme:", "signature:", "states:"):
                self.assertIn(field, " ".join(lines[:2]), name)
            head = "\n".join(lines[:40])
            self.assertIn("pre-emit critique", head, name)
            self.assertLess(head.index("pre-emit critique"), head.index(":root"), name)

    def test_status_badge_is_sentence_case_without_a_dot(self):
        for name in ALL_PAGES:
            badges = page_of(name).find("span", "badge")
            self.assertEqual(len(badges), 1, name)
            self.assertIn(Page.text_of(badges[0]), ("Clean run", "Retried", "Stage failed", NOT_RECORDED), name)
            self.assertEqual(badges[0]["kids"], [], name + ": badge holds only text, no status dot")


# ============================================================================ 5. contrast

class Contrast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tokens = root_tokens(page_of("normal").css)

    def hexes(self, names):
        for key in names:
            self.assertIn(key, self.tokens, key)
            self.assertRegex(self.tokens[key], r"^#[0-9a-fA-F]{6}$", key)
        return dict((key, self.tokens[key]) for key in names)

    def test_background_and_border_tokens(self):
        self.assertEqual(self.tokens["--bg"].lower(), BG)
        self.assertEqual(re.sub(r"\s", "", self.tokens["--rule"]), "rgba(255,255,255,0.08)")
        checked = 0
        for prelude, decls, _ in outside_root(page_of("normal").css):
            for prop, value in decls:
                if prop.startswith("border") and "var(--rule)" in value:
                    checked += 1
                    self.assertRegex(value, r"(^|\s)1px\b", "%s { %s: %s }" % (prelude, prop, value))
        self.assertGreater(checked, 0)

    def test_text_tokens_reach_4_5_on_the_page_and_card_backgrounds(self):
        text = self.hexes(["--ink", "--ink-2", "--muted", "--fail", "--ok-ink", "--warn-ink", "--focus"])
        for surface in ("--bg", "--surface"):
            base = self.hexes([surface])[surface]
            for key, value in text.items():
                self.assertGreaterEqual(contrast(value, base), 4.5, "%s on %s = %.2f" % (key, surface, contrast(value, base)))

    def test_badge_text_reaches_4_5_on_its_own_fill(self):
        for fg, bg in (("--ok-ink", "--ok-bg"), ("--warn-ink", "--warn-bg"), ("--muted", "--surface-2")):
            colours = self.hexes([fg, bg])
            self.assertGreaterEqual(contrast(colours[fg], colours[bg]), 4.5, "%s on %s" % (fg, bg))

    def test_chart_colours_reach_3_to_1_on_the_background(self):
        chart = self.hexes(["--agent-main", "--agent-green", "--agent-red", "--agent-yellow", "--agent-blue",
                            "--ok", "--fail", "--edge"])
        for key, value in chart.items():
            self.assertGreaterEqual(contrast(value, BG), 3.0, "%s = %.2f" % (key, contrast(value, BG)))
        surface = self.hexes(["--surface"])["--surface"]
        self.assertGreaterEqual(contrast(chart["--edge"], surface), 3.0, "button border on the card surface")

    def test_segment_count_labels_are_readable_on_every_segment(self):
        on = self.hexes(["--on-data"])["--on-data"]
        for key in ("--agent-main", "--agent-green", "--agent-red", "--agent-yellow", "--agent-blue"):
            self.assertGreaterEqual(contrast(on, self.hexes([key])[key]), 4.5, key)

    def test_the_five_agent_colours_are_distinct(self):
        colours = [self.tokens[k].lower() for k in ("--agent-main", "--agent-green", "--agent-red", "--agent-yellow", "--agent-blue")]
        self.assertEqual(len(set(colours)), 5)

    def test_contrast_helper_matches_known_values(self):
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(contrast("#777777", "#ffffff"), 4.48, places=1)


# ============================================================================ 6. content without JavaScript

class NoJsContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = page_of("normal")
        cls.graph = load_fixture("synthetic-mission-report.jsonld")["@graph"]
        cls.metrics = load_fixture("synthetic-metrics.json")

    def test_every_kpi_figure_is_in_the_static_markup(self):
        kpis = kpi_map(self.page)
        self.assertEqual(list(kpis), ["Duration", "Files changed", "Tests passed", "Autonomy clean runs"])
        for label, (figure, _) in kpis.items():
            self.assertTrue(figure and figure != NOT_RECORDED, label)

    def test_agent_cards_and_stage_meters_are_in_the_static_markup(self):
        cards = self.page.find("article", "agent")
        names = [Page.text_of(card["kids"][0]["kids"][1]["kids"][0]) for card in cards]
        self.assertEqual(names, ["Black Agent", "Green Agent", "Red Agent", "Yellow Agent", "Blue Agent"])
        stages = [Page.text_of([k for k in li["kids"] if k["tag"] == "h3"][0]) for li in self.page.find("li", "stage")]
        self.assertEqual(stages, ["Orchestrator", "Data", "Analysis", "Action", "Defense/Audit"])
        for li in self.page.find("li", "stage"):
            self.assertEqual(len([k for k in li["kids"] if k["tag"] == "div"]), 2)
        self.assertEqual(len(self.page.find("svg", "bar")), 10)
        self.assertEqual(len(self.page.find("svg", "donut")), 1)

    def test_every_file_path_is_in_the_static_markup(self):
        wanted = set()
        for node in self.graph:
            for obj in node.get("object", []):
                wanted.add(obj["@id"][len("urn:voltron:file:"):])
        wanted.update(f["path"] for f in self.metrics["files"])
        shown = set(Page.text_of(c) for c in self.page.find("code", "fpath"))
        self.assertEqual(shown, wanted)

    def test_copy_buttons_stay_hidden_until_script_runs(self):
        buttons = self.page.find("button")
        self.assertEqual(len(buttons), len(self.page.find("code", "fpath")))
        self.assertGreater(len(buttons), 0)
        for button in buttons:
            self.assertIn("hidden", button["attr_names"])
        self.assertRegex(strip_comments(self.page.css), r"\.copy\[hidden\]\s*\{\s*display:\s*none")
        self.assertRegex(self.page.js, r"\.hidden\s*=\s*false")

    def test_accordion_is_native_details_with_the_file_lists_inside(self):
        details = self.page.find("details")
        groups = [d for d in details if "group" in d["classes"]]
        with_files = len([n for n in self.graph if n.get("object")])
        self.assertEqual(len(groups), with_files + 1)
        self.assertGreaterEqual(len(details), len(groups) + 3)
        for rec in details:
            self.assertNotIn("open", rec["attr_names"])
        for group in groups:
            self.assertEqual([k["tag"] for k in group["kids"]], ["summary", "ul"])
            self.assertTrue(group["kids"][1]["kids"])

    def test_script_only_reveals_buttons_and_copies_text(self):
        js = self.page.js
        self.assertEqual(re.findall(r"createElement\(\s*[\"'](\w+)[\"']", js), ["textarea"])
        self.assertEqual(re.findall(r"querySelectorAll\(\s*([\"'][^\"']+[\"'])", js), ['"button[data-path]"'])
        self.assertIn("dataset.path", js)
        self.assertIn("textContent", js)

    def test_removing_the_script_changes_no_content(self):
        stripped = re.sub(r"<script>.*?</script>", "", self.page.source, flags=re.S)
        again = Page(stripped)
        self.assertEqual(again.errors, [])
        self.assertEqual(again.text, self.page.text)
        self.assertEqual(len(again.find("code", "fpath")), len(self.page.find("code", "fpath")))
        self.assertEqual(len(again.find("article", "agent")), 5)

# ============================================================================ 7. data honesty

class DataHonesty(unittest.TestCase):
    def test_missing_figures_say_not_recorded_and_never_zero(self):
        page = page_of("bare")
        kpis = kpi_map(page)
        self.assertEqual(len(kpis), 4)
        for label, (figure, _) in kpis.items():
            self.assertEqual(figure, NOT_RECORDED, label)
        self.assertEqual(Page.text_of(page.find("span", "badge")[0]), NOT_RECORDED)
        self.assertNotIn("+0", page.text)
        self.assertNotRegex(page.text, r"\b0m 00s\b|\b0s\b|\b0/0\b")
        for dd in page.find("dd", "fig"):
            self.assertNotRegex(Page.text_of(dd), r"^[+~-]?0", "figure printed as zero")
        operator = [Page.text_of(r) for r in page.find("dd")
                    if r["parent"]["kids"][0]["tag"] == "dt" and Page.text_of(r["parent"]["kids"][0]) == "Operator level"]
        self.assertEqual(operator, [NOT_RECORDED])

    def test_partial_metrics_leave_the_other_figures_unrecorded(self):
        cases = (
            ("started-only", {"started_at": "2026-01-05T09:00:00Z"}, "Duration"),
            ("reversed-times", {"started_at": "2026-01-05T10:00:00Z", "ended_at": "2026-01-05T09:00:00Z"}, "Duration"),
            ("tests-without-counts", {"tests": [{"name": "unit", "command": "x"}]}, "Tests passed"),
            ("no-files-key", {"started_at": "2026-01-05T09:00:00Z", "ended_at": "2026-01-05T09:01:00Z"}, "Files changed"),
        )
        for label, data, kpi in cases:
            path = write_json(os.path.join(WORK, "partial-%s.json" % label), dict(data, mission=SLUG))
            out = os.path.join(WORK, "partial-%s.html" % label)
            proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, None, path, level=None))
            self.assertEqual(proc.returncode, 0, proc.err)
            self.assertEqual(kpi_map(Page(read_text(out)))[kpi][0], NOT_RECORDED, label)

    def test_an_empty_file_list_is_a_recorded_zero_not_a_gap(self):
        path = write_json(os.path.join(WORK, "empty-files.json"), {"mission": SLUG, "files": []})
        out = os.path.join(WORK, "empty-files.html")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, None, path, level=None))
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertEqual(kpi_map(Page(read_text(out)))["Files changed"][0], "+0 ~0 -0")

    def test_numbers_equal_the_fixture_inputs(self):
        page = page_of("normal")
        metrics = load_fixture("synthetic-metrics.json")
        kpis = kpi_map(page)
        counts = dict((s, len([f for f in metrics["files"] if f["status"] == s])) for s in ("add", "edit", "del"))
        self.assertEqual(kpis["Files changed"][0], "+%d ~%d -%d" % (counts["add"], counts["edit"], counts["del"]))
        self.assertEqual(kpis["Tests passed"][0], str(sum(t["passed"] for t in metrics["tests"])))
        self.assertEqual(kpis["Tests passed"][1], "%d failed, %d skipped" % (
            sum(t["failed"] for t in metrics["tests"]), sum(t["skipped"] for t in metrics["tests"])))
        suites = [Page.text_of(li) for li in gate_items(page)
                  if li["kids"] and li["kids"][0]["tag"] == "strong" and Page.text_of(li["kids"][0]) in ("unit", "lint")]
        self.assertEqual(len(suites), 2)
        for suite, row in zip(suites, metrics["tests"]):
            self.assertIn("passed %d, failed %d, skipped %d" % (row["passed"], row["failed"], row["skipped"]), suite)
            self.assertIn(row["command"], suite)
        self.assertEqual(kpis["Duration"][0], "14m 32s")
        self.assertEqual(kpis["Autonomy clean runs"][0], "1/5")

    def test_assignment_and_file_counts_per_agent_equal_the_report(self):
        page = page_of("normal")
        graph = load_fixture("synthetic-mission-report.jsonld")["@graph"]
        actions = [n for n in graph if n.get("@type") == "Action"]
        total = len(actions)
        self.assertEqual(page.find("svg", "donut")[0]["attrs"]["aria-label"].split(" in total")[0],
                         "Assignments per Agent, %d" % total)
        by_agent = {}
        for node in actions:
            by_agent.setdefault(node["agent"]["@id"].rsplit(":", 1)[1], []).append(node)
        for key, card in zip(["main", "green", "red", "yellow", "blue"], page.find("article", "agent")):
            cells = [" ".join(Page.text_of(k) for k in d["kids"]) for d in card["kids"][1]["kids"]]
            rows = by_agent.get(key, [])
            if not rows:
                self.assertEqual(cells[0], "Assignments None dispatched")
                continue
            files = set(o["@id"] for r in rows for o in r.get("object", []))
            self.assertEqual(cells[0], "Assignments %d (%d%%)" % (len(rows), int(round(100.0 * len(rows) / total))))
            self.assertEqual(cells[1], "Files %d" % len(files) if files else "Files None listed")

    def test_status_badge_reads_clean_run_or_retried(self):
        self.assertEqual(Page.text_of(page_of("normal").find("span", "badge")[0]), "Clean run")
        self.assertEqual(Page.text_of(page_of("retried").find("span", "badge")[0]), "Retried")
        self.assertEqual(Page.text_of(page_of("bare").find("span", "badge")[0]), NOT_RECORDED)

    def test_autonomous_unlocked_appears_only_for_an_autonomous_verdict(self):
        for name in ("normal", "retried", "bare", "hostile", "hostile_level"):
            self.assertNotRegex(page_of(name).source, r"(?i)unlock", name)
        auto = page_of("auto")
        self.assertEqual(len(re.findall(r"(?i)unlocked", auto.text)), 1)
        kpis = kpi_map(auto)
        self.assertRegex(kpis["Autonomy clean runs"][1], r"^Autonomous unlocked for Fixture alpha")
        self.assertEqual(kpis["Autonomy clean runs"][0], "5/5")
        self.assertNotRegex(auto.text, r"(?i)unlocked for Fixture beta")
        beta = [Page.text_of(li) for li in gate_items(auto) if Page.text_of(li).startswith("Fixture beta")]
        self.assertEqual(len(beta), 1)
        self.assertIn("Actionlist", beta[0])
        self.assertNotRegex(beta[0], r"(?i)unlock")

    def test_mode_label_matches_the_gate_verdict(self):
        self.assertEqual(kpi_map(page_of("normal"))["Autonomy clean runs"][1], "Actionlist mode for Fixture recon")
        gate_text = " ".join(Page.text_of(li) for li in gate_items(page_of("auto")))
        self.assertRegex(gate_text, r"Fixture alpha[^.]*Autonomous, 5 of 5 clean runs")
        self.assertRegex(gate_text, r"Fixture beta[^.]*Actionlist, 1 of 5 clean runs")

    def test_without_a_registry_no_stage_rate_is_invented(self):
        page = page_of("bare")
        for li in page.find("li", "stage"):
            self.assertEqual(Page.text_of(li).count(NOT_RECORDED), 2)
        self.assertEqual(page.find("svg", "bar"), [])


# ============================================================================ 8. determinism

class Determinism(unittest.TestCase):
    def render_to(self, directory, filename="mission-report.html", cwd=None, generated=GENERATED):
        os.makedirs(directory, exist_ok=True)
        out = os.path.join(directory, filename)
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, fx("synthetic-registry.json"),
                                   fx("synthetic-metrics.json"), generated=generated), cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.err)
        with open(out, "rb") as fh:
            return fh.read()

    def test_same_inputs_and_generated_at_give_identical_bytes(self):
        first = self.render_to(os.path.join(WORK, "det-a"))
        second = self.render_to(os.path.join(WORK, "det-b"), filename="other-name.html", cwd=os.path.join(WORK, "det-a"))
        self.assertEqual(first, second)

    def test_generated_at_changes_only_the_timestamp(self):
        a = self.render_to(os.path.join(WORK, "det-c"), generated="2026-01-05T09:20:00Z").decode("utf-8")
        b = self.render_to(os.path.join(WORK, "det-d"), generated="2026-02-06T11:22:00Z").decode("utf-8")
        self.assertNotEqual(a, b)
        self.assertEqual(a.replace("2026-01-05T09:20:00Z", "T").replace("2026-01-05 09:20 UTC", "U"),
                         b.replace("2026-02-06T11:22:00Z", "T").replace("2026-02-06 11:22 UTC", "U"))

    def test_without_generated_at_the_metrics_end_time_is_used(self):
        a = self.render_to(os.path.join(WORK, "det-e"), generated=None)
        b = self.render_to(os.path.join(WORK, "det-f"), generated=None)
        self.assertEqual(a, b)
        self.assertIn(b'datetime="2026-01-05T09:14:32Z"', a)

    def test_output_is_utf8_lf_and_under_the_size_budget(self):
        for name in ALL_PAGES:
            page_of(name)
            with open(os.path.join(WORK, name + ".html"), "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"\r", raw, name)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            raw.decode("utf-8")
            self.assertLess(len(raw), PAGE_BUDGET, "%s is %d bytes" % (name, len(raw)))


# ============================================================================ 9. CLI

class Cli(unittest.TestCase):
    def one_line(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, "expected a one-line message, got %r" % text)
        self.assertNotIn("Traceback", text)

    def test_metrics_rejects_git_base_that_starts_with_a_dash(self):
        for value in ("-x", "--output=evil", "--exec=calc", "-"):
            out = os.path.join(WORK, "metrics-bad.json")
            proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--git-base=" + value])
            self.assertNotEqual(proc.returncode, 0, value)
            self.one_line(proc.err)
            self.assertFalse(os.path.exists(out), "no metrics file may be written for %r" % value)
            self.assertFalse(os.path.exists(os.path.join(WORK, "evil")), value)

    def test_metrics_rejects_git_base_with_whitespace_or_control_characters(self):
        for value in ("main branch", "main\tbranch", "main\nbranch", "ma\x01in", " main", "main "):
            out = os.path.join(WORK, "metrics-ws.json")
            proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--git-base=" + value])
            self.assertNotEqual(proc.returncode, 0, repr(value))
            self.one_line(proc.err)
            self.assertFalse(os.path.exists(out), repr(value))

    def test_metrics_rejects_empty_git_base_and_malformed_values(self):
        cases = (["--git-base="], ["--started-at", "yesterday"], ["--ended-at", "13/45/2026"],
                 ["--test", "only,three,parts"], ["--test", "n,cmd,x,0,0"], ["--test", "n,cmd,-1,0,0"],
                 ["--test", ",cmd,1,0,0"])
        for extra in cases:
            out = os.path.join(WORK, "metrics-inv.json")
            proc = run_cli(["metrics", "--out", out, "--mission", SLUG] + extra)
            self.assertNotEqual(proc.returncode, 0, extra)
            self.one_line(proc.err)
            self.assertFalse(os.path.exists(out), extra)

    def test_metrics_writes_the_documented_keys(self):
        out = os.path.join(WORK, "metrics-ok.json")
        proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--started-at", "2026-01-05T09:00:00+02:00",
                        "--ended-at", "2026-01-05T09:14:32Z",
                        "--test", "unit,python -m unittest discover -s a,b,142,0,3", "--test", "lint,ruff,,,"])
        self.assertEqual(proc.returncode, 0, proc.err)
        data = json.loads(read_text(out))
        self.assertEqual(data["mission"], SLUG)
        self.assertEqual(data["started_at"], "2026-01-05T07:00:00Z")
        self.assertEqual(data["tests"][0], {"name": "unit", "command": "python -m unittest discover -s a,b",
                                            "passed": 142, "failed": 0, "skipped": 3})
        self.assertEqual(data["tests"][1], {"name": "lint", "command": "ruff"})
        self.assertNotIn("files", data)

    def test_render_fails_cleanly_when_the_report_is_missing(self):
        out = os.path.join(WORK, "never.html")
        proc = run_cli(render_args(os.path.join(WORK, "no-such-report.jsonld"), out))
        self.assertNotEqual(proc.returncode, 0)
        self.one_line(proc.err)
        self.assertFalse(os.path.exists(out))

    def test_render_fails_cleanly_on_unparsable_input(self):
        bodies = {"garbage": b"{not json", "empty": b"", "no-graph": b'{"@context": "x"}', "scalar": b"42",
                  "not-utf8": b"\xff\xfe\x00\x00", "graph-not-list": b'{"@graph": {"a": 1}}'}
        for label, body in sorted(bodies.items()):
            report = os.path.join(WORK, "bad-%s.jsonld" % label)
            with open(report, "wb") as fh:
                fh.write(body)
            out = os.path.join(WORK, "bad-%s.html" % label)
            proc = run_cli(render_args(report, out))
            self.assertNotEqual(proc.returncode, 0, label)
            self.one_line(proc.err)
            self.assertFalse(os.path.exists(out), label)

    def test_render_fails_cleanly_when_the_report_is_a_directory(self):
        out = os.path.join(WORK, "dir-report.html")
        proc = run_cli(render_args(WORK, out))
        self.assertNotEqual(proc.returncode, 0)
        self.one_line(proc.err)
        self.assertFalse(os.path.exists(out))

    def test_render_rejects_a_bad_generated_at(self):
        out = os.path.join(WORK, "bad-ts.html")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, generated="not-a-time"))
        self.assertNotEqual(proc.returncode, 0)
        self.one_line(proc.err)
        self.assertFalse(os.path.exists(out))

    def test_a_failed_render_leaves_an_existing_output_untouched(self):
        out = os.path.join(WORK, "keep.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("previous report")
        proc = run_cli(render_args(os.path.join(WORK, "missing.jsonld"), out))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(read_text(out), "previous report")

    def test_output_goes_only_to_out_and_leaves_no_temp_files(self):
        directory = os.path.join(WORK, "only-out")
        os.makedirs(directory)
        pycache = os.path.join(SRC_SCRIPTS, "__pycache__")
        existed = os.path.exists(pycache)
        out = os.path.join(directory, "mission-report.html")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, fx("synthetic-registry.json"),
                                   fx("synthetic-metrics.json")))
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertEqual(os.listdir(directory), ["mission-report.html"])
        if not existed and os.path.dirname(RENDERER) == SRC_SCRIPTS:
            self.assertFalse(os.path.exists(pycache), "the renderer must not write bytecode next to its source")

    def test_output_replaces_an_existing_symlink_without_writing_through_it(self):
        directory = os.path.join(WORK, "symlink")
        os.makedirs(directory)
        target = os.path.join(directory, "victim.txt")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("keep me")
        link = os.path.join(directory, "mission-report.html")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlinks are not available here")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), link))
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertEqual(read_text(target), "keep me")
        self.assertFalse(os.path.islink(link))

    def test_missing_subcommand_and_required_flags_exit_non_zero(self):
        self.assertNotEqual(run_cli([]).returncode, 0)
        self.assertNotEqual(run_cli(["render"]).returncode, 0)
        self.assertNotEqual(run_cli(["metrics", "--out", os.path.join(WORK, "x.json")]).returncode, 0)
        self.assertNotEqual(run_cli(["frobnicate"]).returncode, 0)

# ============================================================================ 10. build

class Build(unittest.TestCase):
    TARGETS = ("claude", "opencode", "codex", "antigravity")

    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp(prefix="dash-build-")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build.py"), "--target", "all", "--out", cls.out],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
        if proc.returncode != 0:
            raise AssertionError("build failed: %s" % proc.stderr.decode("utf-8", "replace"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def script_dir(self, target):
        found = []
        for dirpath, _, files in os.walk(os.path.join(self.out, target)):
            if "render_dashboard.py" in files and os.path.basename(os.path.dirname(dirpath)) == "mission-report":
                found.append(dirpath)
        self.assertEqual(len(found), 1, "%s: %s" % (target, found))
        return found[0]

    def test_both_scripts_are_present_and_identical_to_src_in_every_target(self):
        for target in self.TARGETS:
            directory = self.script_dir(target)
            for name in ("render_dashboard.py", "dashboard_template.py"):
                with open(os.path.join(SRC_SCRIPTS, name), "rb") as fh:
                    source = fh.read().replace(b"\r\n", b"\n")
                with open(os.path.join(directory, name), "rb") as fh:
                    built = fh.read()
                self.assertEqual(built, source, "%s/%s differs from src" % (target, name))

    def test_codex_scripts_land_under_agents_skills(self):
        rel = os.path.relpath(self.script_dir("codex"), os.path.join(self.out, "codex")).replace(os.sep, "/")
        self.assertEqual(rel, ".agents/skills/mission-report/scripts")

    def test_maturity_script_sits_where_the_renderer_looks_for_it(self):
        for target in self.TARGETS:
            directory = os.path.normpath(os.path.join(self.script_dir(target), "..", "..", "actionboard-devops-mission", "scripts"))
            for name in ("maturity.py", "gate_check.py"):
                self.assertTrue(os.path.isfile(os.path.join(directory, name)), "%s: %s" % (target, name))

    def test_each_built_renderer_writes_the_same_page_as_src(self):
        reference = os.path.join(WORK, "build-reference.html")
        report, registry, metrics = fx("synthetic-mission-report.jsonld"), fx("synthetic-registry.json"), fx("synthetic-metrics.json")
        proc = run_cli(render_args(report, reference, registry, metrics), renderer=DEFAULT_RENDERER)
        self.assertEqual(proc.returncode, 0, proc.err)
        for target in self.TARGETS:
            out = os.path.join(WORK, "built-%s.html" % target)
            script = os.path.join(self.script_dir(target), "render_dashboard.py")
            proc = run_cli(render_args(report, out, registry, metrics), renderer=script)
            self.assertEqual(proc.returncode, 0, "%s: %s" % (target, proc.err))
            self.assertEqual(read_text(out), read_text(reference), target)
            stage_section = read_text(out).split("Stage maturity")[1].split("Touched files")[0]
            self.assertIn("100% across 2 actions", stage_section, target + ": maturity.py was not found or failed")

    def test_built_scripts_carry_no_unresolved_placeholders(self):
        for target in self.TARGETS:
            for name in ("render_dashboard.py", "dashboard_template.py"):
                with open(os.path.join(self.script_dir(target), name), encoding="utf-8") as fh:
                    self.assertNotRegex(fh.read(), r"\{\{(?:skills_root|tool:)", "%s/%s" % (target, name))


# ============================================================================ 11. end to end

def git(args, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    proc = subprocess.run(["git"] + args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("git %s: %s" % (args, proc.stderr.decode("utf-8", "replace")))
    return proc.stdout.decode("utf-8", "replace")


def have_git():
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def write_file(path, body):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)


class EndToEnd(unittest.TestCase):
    def test_skill_documents_only_flags_the_cli_accepts(self):
        with open(os.path.join(ROOT, "src", "skills", "mission-report", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        for sub in ("metrics", "render"):
            match = re.search(r"render_dashboard\.py %s((?:[^\n]*\\\n)*[^\n]*)" % sub, skill)
            self.assertIsNotNone(match, "SKILL.md does not document `%s`" % sub)
            documented = set(re.findall(r"--[a-z][a-z-]*", match.group(1)))
            self.assertIn("--out", documented)
            helptext = run_cli([sub, "--help"]).out
            for flag in documented:
                self.assertIn(flag, helptext, "SKILL.md documents %s %s which the CLI does not accept" % (sub, flag))

    def test_metrics_then_render_the_way_the_skill_documents(self):
        # SKILL.md step 8: no `git add -N` step; untracked files count as additions, ignored files do not.
        if not have_git():
            self.skipTest("git is not installed")
        repo = os.path.join(WORK, "e2e-repo")
        mission_dir = os.path.join(repo, "docs", "missions", "2026-01-05-synthetic")
        os.makedirs(mission_dir)
        git(["init", "-q"], repo)
        for rel, body in ((".gitignore", "*.log\nbuild/\n"), ("keep.txt", "k\n"), ("edit me.txt", "a\n"), ("gone.txt", "g\n")):
            write_file(os.path.join(repo, rel), body)
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", "base"], repo)
        base = git(["rev-parse", "HEAD"], repo).strip()
        write_file(os.path.join(repo, "edit me.txt"), "b\n")
        os.unlink(os.path.join(repo, "gone.txt"))
        for rel in ("src_new.py", "second_new.py", "debug.log"):
            write_file(os.path.join(repo, rel), "x\n")
        os.makedirs(os.path.join(repo, "build"))
        write_file(os.path.join(repo, "build", "out.bin"), "x\n")

        metrics = os.path.join(mission_dir, "mission-metrics.json")
        proc = run_cli(["metrics", "--out", metrics, "--mission", SLUG, "--started-at", "2026-01-05T09:00:00Z",
                        "--ended-at", "2026-01-05T09:14:32Z", "--git-base", base,
                        "--test", "unit,python -m unittest discover -s tests -v,142,0,3"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.err)
        statuses = dict((f["path"], f["status"]) for f in json.loads(read_text(metrics))["files"])
        self.assertEqual(statuses, {"edit me.txt": "edit", "gone.txt": "del", "src_new.py": "add", "second_new.py": "add"})

        shutil.copy(fx("synthetic-mission-report.jsonld"), os.path.join(mission_dir, "mission-report.jsonld"))
        os.makedirs(os.path.join(repo, ".actionboard"))
        shutil.copy(fx("synthetic-registry.json"), os.path.join(repo, ".actionboard", "registry.json"))
        html_out = os.path.join(mission_dir, "mission-report.html")
        proc = run_cli(["render", "--report", os.path.join(mission_dir, "mission-report.jsonld"), "--mission", SLUG,
                        "--out", html_out, "--registry", os.path.join(repo, ".actionboard", "registry.json"),
                        "--metrics", metrics, "--operator-level", "L4"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertEqual(proc.err, "")
        page = Page(read_text(html_out))
        self.assertEqual(page.errors, [])
        kpis = kpi_map(page)
        self.assertEqual(kpis["Files changed"][0], "+2 ~1 -1")
        self.assertEqual(kpis["Tests passed"][0], "142")
        self.assertEqual(kpis["Duration"][0], "14m 32s")
        self.assertEqual(Page.text_of(page.find("span", "badge")[0]), "Clean run")
        self.assertEqual(sorted(os.listdir(mission_dir)), ["mission-metrics.json", "mission-report.html", "mission-report.jsonld"])

    def test_untracked_files_are_counted_and_gitignored_ones_are_not(self):
        if not have_git():
            self.skipTest("git is not installed")
        repo = os.path.join(WORK, "e2e-untracked")
        os.makedirs(os.path.join(repo, "sub dir"))
        git(["init", "-q"], repo)
        write_file(os.path.join(repo, ".gitignore"), "*.log\nbuild/\n")
        write_file(os.path.join(repo, "a.txt"), "a\n")
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", "base"], repo)
        write_file(os.path.join(repo, "new.txt"), "n\n")
        write_file(os.path.join(repo, "sub dir", "new two.txt"), "n\n")
        write_file(os.path.join(repo, "debug.log"), "x\n")
        os.makedirs(os.path.join(repo, "build"))
        write_file(os.path.join(repo, "build", "out.bin"), "x\n")
        expected = {"new.txt": "add", "sub dir/new two.txt": "add"}
        out = os.path.join(WORK, "untracked-root.json")
        proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--git-base", "HEAD"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.err)
        got = dict((f["path"], f["status"]) for f in json.loads(read_text(out))["files"])
        self.assertEqual(got, expected)
        with open(os.path.join(ROOT, "src", "skills", "mission-report", "SKILL.md"), encoding="utf-8") as fh:
            self.assertNotIn("git add -N", fh.read())
    def test_git_failures_are_one_line_errors_and_write_nothing(self):
        if not have_git():
            self.skipTest("git is not installed")
        outside = os.path.join(WORK, "not-a-repo")
        os.makedirs(outside)
        out = os.path.join(outside, "m.json")
        proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--git-base", "no-such-ref-xyz"], cwd=outside)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(len([ln for ln in proc.err.splitlines() if ln.strip()]), 1, proc.err)
        self.assertFalse(os.path.exists(out))


# ============================================================================ data injection

class DataInjection(unittest.TestCase):
    """File paths are record data and must never be rewritten (agent-written prose is discussed in the report)."""

    @classmethod
    def setUpClass(cls):
        cls.page = page_of("injection")
        graph = load_fixture("synthetic-injection-report.jsonld")["@graph"]
        cls.paths = [o["@id"][len("urn:voltron:file:"):] for o in graph[1]["object"]]

    def test_file_paths_are_never_altered(self):
        shown = [Page.text_of(c) for c in self.page.find("code", "fpath")]
        copied = [b["attrs"]["data-path"] for b in self.page.find("button")]
        self.assertEqual(len(self.paths), 6)
        for path in self.paths:
            self.assertIn(path, shown)
            self.assertIn(path, copied)
            self.assertIn(html.escape(path, quote=True), self.page.source)
        self.assertEqual(sorted(set(shown)), sorted(set(self.paths)))

    def test_metrics_file_paths_are_never_altered(self):
        shown = set(Page.text_of(c) for c in self.page.find("code", "fpath"))
        for item in load_fixture("synthetic-injection-metrics.json")["files"]:
            self.assertIn(item["path"], shown)

    def test_mission_id_is_never_altered(self):
        self.assertIn(SLUG, [Page.text_of(r) for r in self.page.find("dd", "mono")])


# ============================================================================ known defects

class Hardening(unittest.TestCase):
    """Defects found in the two review rounds; all fixed by Red's follow-up rounds and kept as regression tests."""

    def test_definition_list_children_follow_the_html_content_model(self):
        # <div> inside <dl> may hold only <dt> and <dd>; the KPI cards also hold <p> and <details>.
        bad = []
        for dl in page_of("normal").find("dl"):
            for div in [k for k in dl["kids"] if k["tag"] == "div"]:
                bad.extend(k["tag"] for k in div["kids"] if k["tag"] not in ("dt", "dd"))
        self.assertEqual(bad, [])

    def test_test_commands_are_shown_verbatim(self):
        commands = [Page.text_of(c) for c in page_of("injection").find("code") if "fpath" not in c["classes"]]
        self.assertEqual(commands, ["python -m unittest -k unlock"])

    def test_agent_prose_keeps_its_capitalisation(self):
        text = [Page.text_of(p) for p in page_of("injection").find("p") if "log in" in Page.text_of(p)]
        self.assertEqual(len(text), 1)
        self.assertIn("Unlocked users can log in", text[0])

    def test_a_failed_stage_is_not_reported_as_a_clean_run(self):
        # maturity.py counts a run as clean only when all five stages passed.
        data = load_fixture("synthetic-registry.json")
        data["actions"][0]["runs"][0]["stages"]["action"] = False
        registry = write_json(os.path.join(WORK, "failed-stage-registry.json"), data)
        out = os.path.join(WORK, "failed-stage.html")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, registry, fx("synthetic-metrics.json")))
        self.assertEqual(proc.returncode, 0, proc.err)
        badge = Page(read_text(out)).find("span", "badge")[0]
        self.assertEqual(Page.text_of(badge), "Stage failed")
        self.assertNotIn("badge-ok", badge["classes"])

    def test_deeply_nested_json_is_a_one_line_error(self):
        report = os.path.join(WORK, "deep.jsonld")
        with open(report, "w", encoding="utf-8") as fh:
            fh.write("[" * 200000 + "]" * 200000)
        proc = run_cli(render_args(report, os.path.join(WORK, "deep.html")))
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.err)

    def test_unicode_digits_in_a_test_count_are_a_one_line_error(self):
        proc = run_cli(["metrics", "--out", os.path.join(WORK, "uni.json"), "--mission", SLUG, "--test", "n,c,\u00b2,0,0"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.err)

    def test_out_of_range_timestamps_are_a_one_line_error(self):
        proc = run_cli(["metrics", "--out", os.path.join(WORK, "year.json"), "--mission", SLUG,
                        "--started-at", "9999-12-31T23:59:59-05:00"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.err)

    def test_a_registry_with_malformed_runs_does_not_crash_the_render(self):
        registry = write_json(os.path.join(WORK, "bad-runs.json"),
                              {"actions": [{"id": "a", "name": "A", "risk_tier": "T2", "missions": [SLUG], "runs": 5}]})
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), os.path.join(WORK, "bad-runs.html"), registry))
        self.assertNotIn("Traceback", proc.err)

    def test_out_may_not_overwrite_the_report_input(self):
        report = os.path.join(WORK, "same.jsonld")
        shutil.copy(fx("synthetic-mission-report.jsonld"), report)
        proc = run_cli(render_args(report, report))
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(read_text(report).lstrip().startswith("{"))

    def test_out_pointing_at_a_directory_is_a_one_line_error(self):
        directory = os.path.join(WORK, "as-dir")
        os.makedirs(directory)
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), directory))
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.err)

# ============================================================================ behaviour added by the follow-up round

def render_with(report=None, registry=None, metrics=None, out_name="x.html", level="L4", extra=(), cwd=None, slug=SLUG):
    out = os.path.join(WORK, out_name)
    args = ["render", "--report", report or fx("synthetic-mission-report.jsonld"), "--mission", slug, "--out", out,
            "--generated-at", GENERATED]
    if registry:
        args += ["--registry", registry]
    if metrics:
        args += ["--metrics", metrics]
    if level:
        args += ["--operator-level", level]
    proc = run_cli(args + list(extra), cwd=cwd)
    proc.out_path = out
    return proc


def report_with_files(paths, name="files.jsonld"):
    graph = load_fixture("synthetic-mission-report.jsonld")
    for node in graph["@graph"]:
        node.pop("object", None)
        if node.get("@id", "").endswith(":assignment:2") and paths:
            node["object"] = [{"@id": "urn:voltron:file:" + p} for p in paths]
    return write_json(os.path.join(WORK, name), graph)

    def test_metrics_run_from_a_subdirectory_still_lists_every_untracked_file(self):
        if not have_git():
            self.skipTest("git is not installed")
        repo = os.path.join(WORK, "e2e-subdir")
        os.makedirs(os.path.join(repo, "sub"))
        git(["init", "-q"], repo)
        write_file(os.path.join(repo, "a.txt"), "a\n")
        git(["add", "-A"], repo)
        git(["commit", "-q", "-m", "base"], repo)
        write_file(os.path.join(repo, "top_new.txt"), "n\n")
        write_file(os.path.join(repo, "sub", "sub_new.txt"), "n\n")
        out = os.path.join(WORK, "untracked-sub.json")
        proc = run_cli(["metrics", "--out", out, "--mission", SLUG, "--git-base", "HEAD"], cwd=os.path.join(repo, "sub"))
        self.assertEqual(proc.returncode, 0, proc.err)
        got = sorted(f["path"] for f in json.loads(read_text(out))["files"])
        self.assertEqual(got, ["sub/sub_new.txt", "top_new.txt"])


class Warnings(unittest.TestCase):
    def warning_lines(self, proc):
        return [ln for ln in proc.err.splitlines() if re.match(r"^(?:render_dashboard: )?WARNING\b", ln)]

    def test_maturity_failure_warns_on_stderr_and_still_writes_the_page(self):
        proc = render_with(registry=fx("synthetic-registry.json"), metrics=fx("synthetic-metrics.json"),
                           level="L9", out_name="warn-level.html")
        self.assertEqual(proc.returncode, 0, proc.err)
        lines = self.warning_lines(proc)
        self.assertEqual(len(lines), 1, proc.err)
        self.assertIn("maturity", lines[0])
        self.assertNotIn("Traceback", proc.err)
        page = Page(read_text(proc.out_path))
        self.assertEqual(page.errors, [])
        self.assertEqual(kpi_map(page)["Autonomy clean runs"][0], NOT_RECORDED)
        for li in page.find("li", "stage"):
            self.assertIn(NOT_RECORDED, Page.text_of(li))
        self.assertEqual(len(page.find("svg", "bar")), 5)  # only the "this mission" bars remain
        self.assertEqual(kpi_map(page)["Duration"][0], "14m 32s")

    def test_a_missing_maturity_script_warns_too(self):
        scripts = os.path.join(WORK, "no-maturity", "skills", "mission-report", "scripts")
        os.makedirs(scripts)
        for name in ("render_dashboard.py", "dashboard_template.py"):
            shutil.copy(os.path.join(os.path.dirname(RENDERER), name), scripts)
        out = os.path.join(WORK, "no-maturity.html")
        proc = run_cli(render_args(fx("synthetic-mission-report.jsonld"), out, fx("synthetic-registry.json"),
                                   fx("synthetic-metrics.json")), renderer=os.path.join(scripts, "render_dashboard.py"))
        self.assertEqual(proc.returncode, 0, proc.err)
        lines = self.warning_lines(proc)
        self.assertEqual(len(lines), 1, proc.err)
        self.assertIn("not found", lines[0])
        self.assertTrue(os.path.exists(out))

    def test_no_warning_without_a_registry_or_with_a_healthy_one(self):
        bare = render_with(level=None, out_name="warn-bare.html", cwd=WORK)
        self.assertEqual(bare.returncode, 0, bare.err)
        self.assertEqual(bare.err, "")
        healthy = render_with(registry=fx("synthetic-registry.json"), metrics=fx("synthetic-metrics.json"),
                              out_name="warn-ok.html")
        self.assertEqual(healthy.returncode, 0, healthy.err)
        self.assertEqual(healthy.err, "")

    def test_skill_describes_the_warning_the_way_the_renderer_prints_it(self):
        proc = render_with(registry=fx("synthetic-registry.json"), level="L9", out_name="warn-doc.html")
        with open(os.path.join(ROOT, "src", "skills", "mission-report", "SKILL.md"), encoding="utf-8") as fh:
            skill = fh.read()
        self.assertRegex(skill, r"line containing `WARNING` on stderr")
        # the renderer prefixes its own name; the SKILL promises only a line that contains WARNING
        self.assertTrue(any("WARNING" in ln for ln in proc.err.splitlines()), proc.err)
        self.assertTrue(all(ln.startswith("render_dashboard: ") for ln in proc.err.splitlines() if ln.strip()), proc.err)


class StageFailedBadge(unittest.TestCase):
    def badge(self, mutate, name):
        data = load_fixture("synthetic-registry.json")
        mutate(data)
        registry = write_json(os.path.join(WORK, name + "-registry.json"), data)
        proc = render_with(registry=registry, metrics=fx("synthetic-metrics.json"), out_name=name + ".html")
        self.assertEqual(proc.returncode, 0, proc.err)
        return Page(read_text(proc.out_path)).find("span", "badge")[0]

    def test_a_failed_stage_on_a_first_attempt_is_the_third_state(self):
        def fail_stage(data):
            data["actions"][0]["runs"][0]["stages"]["data"] = False
        badge = self.badge(fail_stage, "badge-stage")
        self.assertEqual(Page.text_of(badge), "Stage failed")
        self.assertEqual(badge["classes"], ["badge", "badge-warn"])
        self.assertEqual(badge["kids"], [])

    def test_retry_wins_over_a_failed_stage(self):
        def both(data):
            data["actions"][0]["runs"][0]["stages"]["data"] = False
            data["actions"][1]["runs"][0]["first_attempt"] = False
        self.assertEqual(Page.text_of(self.badge(both, "badge-both")), "Retried")

    def test_all_stages_passing_stays_a_clean_run(self):
        badge = self.badge(lambda data: None, "badge-clean")
        self.assertEqual(Page.text_of(badge), "Clean run")
        self.assertIn("badge-ok", badge["classes"])


class UnsafePathsAndCap(unittest.TestCase):
    NORMAL = ["src/ok.py", "docs/caf\u00e9 menu.md", "dir/with space/a&b.txt", "x/\u4e2d\u6587.py"]
    UNSAFE = ["evil\u202egnp.py", "line\nbreak.py", "tab\there.py", "nul\x01byte.py", "esc\x1b[31m.py",
              "iso\u2066late.py", "c1\x85next.py", "del\x7fchar.py"]

    @classmethod
    def setUpClass(cls):
        report = report_with_files(cls.NORMAL + cls.UNSAFE, "unsafe.jsonld")
        proc = render_with(report=report, out_name="unsafe.html")
        assert proc.returncode == 0, proc.err
        cls.source = read_text(proc.out_path)
        cls.page = Page(cls.source)

    def test_control_and_direction_characters_are_shown_as_visible_escapes(self):
        shown = [Page.text_of(c) for c in self.page.find("code", "fpath")]
        for expected in ("evil\\u202egnp.py", "line\\nbreak.py", "tab\\there.py", "nul\\x01byte.py",
                         "esc\\x1b[31m.py", "iso\\u2066late.py", "c1\\x85next.py", "del\\x7fchar.py"):
            self.assertIn(expected, shown)

    def test_no_raw_control_or_direction_character_reaches_the_page(self):
        self.assertIsNone(re.search("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
                                    self.source))
        for rec in self.page.elems:
            for value in rec["attrs"].values():
                self.assertIsNone(re.search("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", value or ""))

    def test_unsafe_paths_get_no_copy_button_and_say_so(self):
        buttons = set(b["attrs"]["data-path"] for b in self.page.find("button"))
        self.assertEqual(buttons, set(self.NORMAL))
        for rec in self.page.find("code", "fpath"):
            text = Page.text_of(rec)
            note = Page.text_of(rec["parent"])
            if "\\" in text:
                self.assertIn("No copy button", note)
                self.assertEqual(rec["parent"]["parent"]["kids"][1:], [], "unsafe row must hold no button")

    def test_normal_paths_keep_a_byte_exact_data_path(self):
        by_path = dict((b["attrs"]["data-path"], b) for b in self.page.find("button"))
        for path in self.NORMAL:
            self.assertIn(path, by_path)
            self.assertEqual(by_path[path]["attrs"]["aria-label"], "Copy path " + path)
            self.assertIn(path, [Page.text_of(c) for c in self.page.find("code", "fpath")])


class FileListCap(unittest.TestCase):
    def render_files(self, count, name):
        paths = ["gen/f%04d.py" % i for i in range(count)]
        report = report_with_files([], name + ".jsonld")
        metrics = write_json(os.path.join(WORK, name + "-metrics.json"), {
            "mission": SLUG, "files": [{"path": p, "status": "add" if i % 3 else "edit"} for i, p in enumerate(paths)]})
        proc = render_with(report=report, metrics=metrics, out_name=name + ".html")
        self.assertEqual(proc.returncode, 0, proc.err)
        return Page(read_text(proc.out_path)), paths

    def test_list_stops_at_1000_with_a_note_while_kpi_counts_stay_exact(self):
        page, paths = self.render_files(1500, "cap-1500")
        self.assertEqual(len(page.find("code", "fpath")), 1000)
        self.assertEqual(len(page.find("button")), 1000)
        notes = [Page.text_of(p) for p in page.find("p", "note") if "more file" in Page.text_of(p)]
        self.assertEqual(notes, ["500 more files not listed; see mission-report.jsonld"])
        edits = len([i for i in range(1500) if i % 3 == 0])
        self.assertEqual(kpi_map(page)["Files changed"][0], "+%d ~%d -0" % (1500 - edits, edits))
        self.assertEqual([Page.text_of(c) for c in page.find("code", "fpath")], paths[:1000])

    def test_exactly_1000_files_has_no_note(self):
        page, _ = self.render_files(1000, "cap-1000")
        self.assertEqual(len(page.find("code", "fpath")), 1000)
        self.assertEqual([p for p in page.find("p", "note") if "more file" in Page.text_of(p)], [])

    def test_one_over_the_cap_is_singular(self):
        page, _ = self.render_files(1001, "cap-1001")
        notes = [Page.text_of(p) for p in page.find("p", "note") if "more file" in Page.text_of(p)]
        self.assertEqual(notes, ["1 more file not listed; see mission-report.jsonld"])

    def test_the_cap_spans_groups(self):
        paths_a = ["a/f%04d.py" % i for i in range(700)]
        report = report_with_files(paths_a, "cap-groups.jsonld")
        metrics = write_json(os.path.join(WORK, "cap-groups-metrics.json"), {
            "mission": SLUG, "files": [{"path": "b/f%04d.py" % i, "status": "add"} for i in range(600)]})
        proc = render_with(report=report, metrics=metrics, out_name="cap-groups.html")
        page = Page(read_text(proc.out_path))
        self.assertEqual(len(page.find("code", "fpath")), 1000)
        self.assertIn("300 more files not listed", page.text)
        self.assertEqual(kpi_map(page)["Files changed"][0], "+600 ~0 -0")

    def test_page_stays_far_below_a_megabyte_at_the_cap(self):
        proc = render_with(report=report_with_files([], "cap-size.jsonld"),
                           metrics=write_json(os.path.join(WORK, "cap-size-metrics.json"), {
                               "mission": SLUG, "files": [{"path": "gen/f%05d.py" % i, "status": "add"} for i in range(20000)]}),
                           out_name="cap-size.html")
        self.assertEqual(proc.returncode, 0, proc.err)
        self.assertLess(os.path.getsize(proc.out_path), 400 * 1024)


class OutputGuards(unittest.TestCase):
    def refuse(self, flag, out_of):
        report = os.path.join(WORK, "guard-report.jsonld")
        registry = os.path.join(WORK, "guard-registry.json")
        metrics = os.path.join(WORK, "guard-metrics.json")
        shutil.copy(fx("synthetic-mission-report.jsonld"), report)
        shutil.copy(fx("synthetic-registry.json"), registry)
        shutil.copy(fx("synthetic-metrics.json"), metrics)
        files = {"--report": report, "--registry": registry, "--metrics": metrics}
        target = out_of(files)
        before = read_text(files[flag])
        proc = run_cli(["render", "--report", report, "--registry", registry, "--metrics", metrics,
                        "--mission", SLUG, "--out", target])
        self.assertNotEqual(proc.returncode, 0, flag)
        lines = [ln for ln in proc.err.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, proc.err)
        self.assertIn(flag, lines[0])
        self.assertEqual(read_text(files[flag]), before, "input was overwritten")

    def test_out_equal_to_each_input_is_refused(self):
        for flag in ("--report", "--registry", "--metrics"):
            self.refuse(flag, lambda files, flag=flag: files[flag])

    def test_a_different_spelling_of_the_same_path_is_refused(self):
        self.refuse("--report", lambda files: os.path.join(WORK, ".", "guard-report.jsonld"))
        self.refuse("--registry", lambda files: os.path.join(WORK, "sub", "..", "guard-registry.json"))

    def test_a_symlink_to_an_input_is_refused(self):
        link = os.path.join(WORK, "guard-link.html")
        shutil.copy(fx("synthetic-mission-report.jsonld"), os.path.join(WORK, "guard-report.jsonld"))
        try:
            if os.path.lexists(link):
                os.unlink(link)
            os.symlink(os.path.join(WORK, "guard-report.jsonld"), link)
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("symlinks are not available here")
        proc = run_cli(["render", "--report", os.path.join(WORK, "guard-report.jsonld"), "--mission", SLUG, "--out", link])
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(read_text(os.path.join(WORK, "guard-report.jsonld")).lstrip().startswith("{"))

    def test_metrics_out_may_not_be_a_directory(self):
        proc = run_cli(["metrics", "--out", WORK, "--mission", SLUG])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(len([ln for ln in proc.err.splitlines() if ln.strip()]), 1, proc.err)
        self.assertNotIn("Traceback", proc.err)

    def test_input_larger_than_the_cap_is_a_one_line_error(self):
        big = os.path.join(WORK, "huge.jsonld")
        with open(big, "wb") as fh:
            fh.write(b'{"@graph": [], "pad": "' + b"x" * (17 * 1024 * 1024) + b'"}')
        proc = run_cli(render_args(big, os.path.join(WORK, "huge.html")))
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(len([ln for ln in proc.err.splitlines() if ln.strip()]), 1, proc.err)
        self.assertFalse(os.path.exists(os.path.join(WORK, "huge.html")))
        os.unlink(big)


class AgentTextVerbatim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = page_of("injection")
        cls.graph = load_fixture("synthetic-injection-report.jsonld")["@graph"]
        cls.metrics = load_fixture("synthetic-injection-metrics.json")

    def test_outcome_text_is_shown_exactly_as_written(self):
        outcome = [r for r in self.graph[1]["result"] if r["name"] == "outcome"][0]["description"]
        shown = [Page.text_of(p) for p in self.page.find("p")]
        self.assertIn(outcome, shown)
        self.assertIn("unlock", outcome.lower())

    def test_assignment_and_test_names_and_commands_are_shown_exactly(self):
        text = self.page.text
        self.assertIn("Assignment 1: " + self.graph[1]["name"], text)
        suite = self.metrics["tests"][0]
        strong = [Page.text_of(r) for r in self.page.find("strong")]
        self.assertIn(suite["name"], strong)
        self.assertIn(suite["command"], [Page.text_of(c) for c in self.page.find("code")])

    def test_unlock_in_agent_text_is_not_rewritten(self):
        self.assertNotRegex(self.page.text, r"(?i)reach(?:es|ed|ing)?")
        self.assertIn("Unlocked users can log in", self.page.text)
        self.assertIn("\u2014", self.page.source)
        self.assertIn("\u2192", self.page.source)

    def test_the_autonomous_label_stays_the_renderers_own_even_when_agents_say_it(self):
        data = load_fixture("synthetic-mission-report.jsonld")
        for node in data["@graph"]:
            if node.get("@id", "").endswith(":assignment:2"):
                node["result"][1]["description"] = "Autonomous unlocked, the agent claims, for this task."
        report = write_json(os.path.join(WORK, "claim.jsonld"), data)
        proc = render_with(report=report, registry=fx("synthetic-registry.json"), metrics=fx("synthetic-metrics.json"),
                           out_name="claim.html")
        page = Page(read_text(proc.out_path))
        self.assertIn("Autonomous unlocked, the agent claims, for this task.", page.text)
        self.assertEqual(kpi_map(page)["Autonomy clean runs"][1], "Actionlist mode for Fixture recon")
        self.assertEqual(len(re.findall("(?i)unlocked", page.text)), 1)


if __name__ == "__main__":
    unittest.main()