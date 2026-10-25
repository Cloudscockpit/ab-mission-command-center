# Dashboard browser verification, 2026-10 (assignment 5)

Page under test: `docs/assets/sample-mission-report.html`, the same file that was measured (sha256 `6c153ae89049059eccaf24c8a9c217f750927d9b98ec0c0b1b66ce318dc808b6`, 36,583 bytes). Renderer state: `render_dashboard.py` and `dashboard_template.py` after Red's defect-fix round (stable since 04:26 on 2026-10-26).

Browser: Chrome 155.0.8059.85 (`C:\Program Files\Google\Chrome\Application\chrome.exe`), headless=new, `--disable-gpu --no-sandbox`, fresh `--user-data-dir` per run, `--log-net-log` with `--net-log-capture-mode=Everything`, driven through puppeteer-core (Red's scratch install). Device scale factor 1. Windows 11.

## Inputs, and where each number came from

Nothing is invented. Mission `zero-footprint-installer-npx-zero-clone-v1-1-0`, operator level L4.

| Input | Value | Source |
|---|---|---|
| Report | `docs/missions/2026-10-26-zero-footprint-installer-npx-zero-clone-v1-1-0/mission-report.jsonld` | 6 assignments (green 1, red 2, yellow 2, blue 1) |
| Registry | `.actionboard/registry.json`, run through `maturity.py` | 6 scored runs for this mission |
| File counts | +15 ~12 -0 (27 files) | `render_dashboard.py metrics --git-base 91a37fe`, run in a clean `git clone` checked out at `cf04e32`, so the diff is exactly `git diff --name-status 91a37fe cf04e32`. The real checkout was not used because it holds uncommitted v1.2.0 files that would count as untracked adds. The CLI needed no hand-written JSON. |
| Tests | 106 passed, 0 failed, 1 skipped, as three suites: `tests/install` 55, `tests/installer` (Python) 23, `tests/installer` (node) 28 passed and 1 skipped | v1.1.0 `mission-report.md` rows 14 and 42 (Yellow's report); commands from `.github/workflows/ci.yml`. Red's earlier run listed only two of the three. |
| Started | 2026-10-25T18:52:22Z | committer time of `91a37fe` (the base commit) |
| Ended | 2026-10-25T20:23:02Z | committer time of `cf04e32` (the closing commit) |
| Duration shown | 1h 30m 40s | end minus start |

Deviation to note: the brief asked for the registry `completed_at` range. All six runs carry `completed_at` between 2026-10-25T19:57:54Z and 19:57:55Z (they were recorded in one batch at report time), which would print "Duration 1s" and mislead. The commit-time span is real but is the span of the commits, not a measured mission clock. Replace `--started-at` and `--ended-at` if a better source exists.

Commands (from the scratch folder):

```
git clone C:/office-work/agent-formation clone && git -C clone checkout cf04e32
cd clone && python render_dashboard.py metrics --out mission-metrics.json --mission <slug> \
  --started-at 2026-10-25T18:52:22Z --ended-at 2026-10-25T20:23:02Z --git-base 91a37fe \
  --test "tests/install,python -m unittest discover -s tests/install -v,55,0,0" \
  --test "tests/installer (python),python -m unittest discover -s tests/installer -v,23,0,0" \
  --test "tests/installer (node),node --test tests/installer/install.test.mjs,28,0,1"
python render_dashboard.py render --report <v1.1.0 mission-report.jsonld> --registry .actionboard/registry.json \
  --metrics mission-metrics.json --mission <slug> --operator-level L4 --out mission-report.html
```

`render` printed nothing on stderr (no WARNING).

## Results per width

Each width was loaded fresh, probed with the accordions closed, then with every `<details>` opened, and screenshotted at full page.

| Width | Horizontal scroll | Clipping or overlap | Tap targets | Requests made by the page |
|---|---|---|---|---|
| 375 | pass (scrollWidth 375 = clientWidth 375, body 375) | pass: 0 clipped elements, 0 overlapping text boxes, closed and open; smallest text 13px (SVG captions render at 19 to 51px) | pass: 40 targets (28 copy buttons, 12 summaries), smallest 44 x 85.2px | pass: 0 non-`file:` requests |
| 768 | pass (768 = 768) | pass (0 clipped, 0 overlaps) | not required; same 40 targets, smallest 44px | pass: 0 |
| 1440 | pass (1440 = 1440) | pass (0 clipped, 0 overlaps) | not required; same | pass: 0 |
| 3840 | pass (3840 = 3840) | pass (0 clipped, 0 overlaps) | not required; same | pass: 0 |

Page height: 4225px at 375, 3047 at 768, 2137 at 1440, 2160 at 3840. Opening and closing every accordion returns the document to its original height (2137 to 5187 to 2137 at 1440).

### Requests: what the net logs contain

Every net log (`--log-net-log`) contains http(s) URLs, but they come from Chrome itself: `clients2.google.com/time`, `update.googleapis.com`, `accounts.google.com`, `www.google.com`, `www.gstatic.com`, `csp.withgoogle.com`, `edgedl.me.gvt1.com`, `android.clients.google.com`. Three controls separate the page from the browser:

1. The same run against `about:blank` produced the identical host list, so the page adds no host.
2. Page-level request events (CDP, via puppeteer `request`) saw only `file:///...mission-report.html` itself (1 to 2 events per run, none http(s)). A positive control (an `<img src="http://example.invalid/x.png">` page) shows `http://example.invalid/x.png` in the same listener, so the method does detect page requests.
3. A second run with `--disable-background-networking --disable-component-update --disable-sync` and similar flags still showed Chrome's own hosts, so the raw count in the net log cannot be made 0 in this Chrome build. The page-attributed count is 0 at every width.

Raw numbers per width (net log http(s) URLs, all browser-originated): 375: 8 to 9, 768: 8, 1440: 12, 3840: 9.

## Other checks

| Check | Result | Evidence |
|---|---|---|
| JS off | pass | With `setJavaScriptEnabled(false)`: 12 `<details>`, 28 file paths (`code.fpath`) in the DOM, 5 Agent cards, 5 stage rows, KPI figures `1h 30m 40s`, `+15 ~12 -0`, `106`, `2/5`; all 28 copy buttons stay hidden (no script ran). Clicking the first group summary opened it (`details[open]` 0 to 1) and the first path `scripts/install.py` rendered at 15px height. |
| Copy under `file://` | pass | `isSecureContext` true, `navigator.clipboard` present; clipboard permission granted for `file://`. Clicked 3 buttons (first, middle, last of 28); `navigator.clipboard.readText()` returned the exact path each time (`scripts/install.py`, `CHANGELOG.md`, `tests/installer/test_installer_py.py`); label changed to "Copied" and the live region read "Copied <path>". Fallback: with `navigator.clipboard` removed, the `execCommand` path ran, label "Copied", and a Ctrl+V into a textarea pasted `scripts/actionboard_uninstall.py`, exact. |
| Console errors | pass | 0 console messages of any type, 0 page errors, 0 failed requests, 0 CSP violation messages at all four widths. |
| prefers-reduced-motion | pass | With `reduce` emulated at 375: `document.getAnimations().length` 0, `.copy` `transition-property: none`, `transition-duration: 0s`, summary arrow `0s`, `scroll-behavior: auto`; `matches` true. The page is fully legible (screenshot `shot-375-reduced.png`, same layout and height 4225px). Without reduction the page also has no running animation (0). |
| Lint | pass with one waiver | `sloplint.mjs <page> --render --scope app`: `0 FAIL, 0 WARN, 1 WAIVED across 1 file(s).` The waived item is gate 72 (`div.card bottom -187px; details.card bottom -96px; details.card bottom -118px` at 1440px). The same result on the normal and the autonomous synthetic fixtures. |

There were no failures, so there are no failure transcripts.

## Visual inspection

The 1440 and 375 screenshots were read as images.

- Dark, flat, hairline-bordered panels on `#0a0c10`; no gradient, glow, purple, glassmorphism or emoji; no oversized padding. Density is moderate: key figures sit in four equal cards at 1440 and stack at 375.
- Contrast is high for the headline figures and labels; the muted captions ("Duration", "Mission ID", "Window pass rate") are visibly dimmer but readable.
- The donut is labelled twice (segment counts and a legend with percentages), so colour is never the only signal. The Black Agent swatch is light grey and visible.
- The stage meters read clearly; the red section of the Action "this mission" bar (3 of 6) stands out against green.
- Minor observations, not failures: the 5th Agent card row at 1440 leaves one empty grid slot; the four KPI cards have unused space under short content; at 3840 the content stays capped at about 1360px wide in the centre of the screen (intended by the floor rule on a capped container, but small on a 4K display). "Retried" is the true status because the registry marks runs of this mission as retried.
- Nothing looked broken. At 375 the header meta block stacks into four short rows, and the long mission id wraps onto two lines without clipping.

## Defects recorded

None from this assignment. Renderer defects found in the second review round are listed in the Yellow report (subdirectory untracked files, SKILL wording of the WARNING prefix).

## Artefacts

- `docs/assets/mission-dashboard-desktop.png`: 1440 x 2137, full page, 133,835 bytes.
- `docs/assets/mission-dashboard-mobile.png`: 375 x 4225, full page, 144,469 bytes.
- `docs/assets/sample-mission-report.html`: the measured page.