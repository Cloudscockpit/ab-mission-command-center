# Dashboard test fixtures (SYNTHETIC)

Every file here is synthetic test data for `tests/report/test_dashboard.py`. None of it
describes a real mission, run or file. Mission slug `synthetic-dashboard-fixture`.

| File | Purpose |
|---|---|
| `synthetic-mission-report.jsonld` | Trimmed report graph: 6 assignments, 4 Agents, one failed assignment, one with an error |
| `synthetic-metrics.json` | Duration 14m 32s, two test suites (142+31 passed), 6 changed files (3 add, 2 edit, 1 del) |
| `synthetic-registry.json` | Two `actionlist` actions with one clean first-attempt run each |
| `synthetic-registry-autonomous.json` | `fixture-alpha` has five clean runs (gate verdict `autonomous` at L4); `fixture-beta` stays `actionlist` |
| `synthetic-hostile-*.{jsonld,json}` | Markup, quote and script breakout strings in every injected field (slug `hostile-slug`) |
| `synthetic-injection-*.{jsonld,json}` | File paths and agent text containing the words and punctuation the renderer rewrites ("unlock", dashes, arrows) |

Registry runs carry no `completed_at` on purpose: `gate_check.py` drops runs older than 90 days,
so a dated fixture would change its gate verdict as the calendar moves.
