# ATLAS Quality Standards
## The rubric behind `.quality/checks.py`

This document is the plain-English rubric for the ATLAS quality engine. It
exists so a human (or a Claude session) can read what each check is
actually doing without crawling through Python.

S2 invariant — **bidirectional sync.** Every `CheckResult("X.Y", "name", …)`
declared in `.quality/checks.py` or `.quality/dimensions/*.py` MUST appear
here as a `### X.Y <name>` heading with the exact same name, and vice versa.
Architecture check **3.10 — Standards doc matches code** runs the
`.quality/verify_doc_matches_code.py` script on every gate run and fails if
either side drifts. Rename a check in code, you rename it here in the same
commit.

---

## Scoring engine (S1 contract)

The engine has **seven independent dimensions**. There is no composite
score. There is no weighted sum. Each dimension stands or falls on its own,
and the gate has a single rule:

> **PASS if every gating dimension scores ≥ 80% of its eligible points.**

- Five dimensions gate: `security`, `code`, `architecture`, `api`,
  `frontend`.
- Two dimensions are informational until V1.6 promotes them: `backend`,
  `product`. They are scored on every run, surfaced in the dashboard, and
  flipped to gating once the underlying tables/criteria exist.

Per-check scoring: each check declares its `max_score`. A check returns a
score from 0 to its max plus an evidence string. SKIP'd checks contribute
neither to the numerator nor the denominator — they are subtracted from
`eligible` so a check that can't run yet doesn't drag a dimension down.

Severity tags (`critical`, `high`, `medium`, `low`, `info`) are advisory
metadata for the dashboard — they do not change the gate verdict.

Full report shape lives in `.quality/report.json`. Dimensions appear under
`dims.<name>` with `score`, `gating`, `passed`, `eligible`, `checks[]`. There
is intentionally no top-level `overall` key.

---

## Dimension 1 — Security  *(gating)*

Protects credentials and the public attack surface. The five-check core
inherited from C5 plus four ATLAS-specific waivers/overlays.

### 1.1 No hardcoded secrets

Regex scan of every tracked source file for API-key/JWT/connection-string
shapes. 0 matches → 20/20, 1–2 → 10/20, 3+ → 0/20. **Plain English:** "Are
passwords or API keys written directly in code instead of environment
variables?" **Fix:** move to env vars, add the placeholder to
`.env.example`. **Severity:** critical.

### 1.2 Environment variable hygiene

Four sub-checks: `.env` in `.gitignore` (3pt), `.env.example` exists (3pt),
no `NEXT_PUBLIC_*SECRET` leaks (4pt), no Supabase service-role references in
client code (5pt — auto-passed since ATLAS uses RDS directly). **Plain
English:** "Are credentials properly hidden from users' browsers?"
**Severity:** high if score < 10.

### 1.3 Dependency vulnerabilities

Runs `pip-audit --format=json` and counts critical/high findings. 0+0 →
15/15, 0 critical and ≤3 high → 10/15, anything else → 0/15. SKIP if
pip-audit isn't installed. **Plain English:** "Do any libraries we use have
known security holes?" **Severity:** critical/high/info.

### 1.4 CORS configuration

Parses every `backend/**/main.py` for `CORSMiddleware`. Specific origins
list → 10/10, wildcard `["*"]` → 0/10, no config at all → 5/10 (secure
default but unintentional). **Plain English:** "Does the server only
accept requests from our own websites?" **Severity:** high if 0.

### 1.5 Authentication coverage

V1.5 product decision: ATLAS is a public dev deployment with auth deferred
until post-V10. The check returns 15/15 with `status="SKIP"` and an
explicit waiver note in the evidence. When auth lands, replace this with
the C5 route-coverage scan. **Severity:** info.

### 1.6 Supabase service role key

ATLAS does not use Supabase, so this returns 10/10 with `status="RUN"`
and an n/a note. The check is kept (rather than dropped) so cross-platform
JIP rubrics stay aligned. **Severity:** info.

### 1.7 HTTPS enforcement

Looks for `infra/nginx.conf` and checks for `return 301 https` or
`listen 443 ssl`. Pass → 5/5. SKIP if the file is absent (set up in the
deploy chunk, not yet provisioned in dev). **Severity:** medium if 0.

### 1.8 Rate limiting

Greps every `.py` file for `slowapi`, `RateLimiter`, or `Limiter(`. Pass →
5/5, fail → 0/5. ATLAS is internal-network only today, but the check
remains so when the public Advisor shell ships in V8 the gate already
flags it. **Severity:** medium if 0.

### 1.9 Input validation

Walks `backend/routes/*.py` and counts route bodies typed as
`SomethingRequest` (Pydantic) vs raw `dict`/`Request`. All Pydantic → 5/5,
>80% Pydantic → 3/5, otherwise 0/5. **Plain English:** "Do we validate
data coming in, or blindly trust it?" **Severity:** high if 0.

### 1.10 No API key leaks in runner logs / spec files

Scans `scripts/forge_runner/`, `.forge/`, and `docs/specs/` for patterns
matching Anthropic API keys (`sk-ant-*`). Any match → 0/5, clean → 5/5.
**Plain English:** "Have we accidentally committed API keys into runner
logs or spec files?" **Severity:** critical if found.

---

### 1.10 No API key leaks in runner logs / spec files

Scans `.forge/logs/**/*`, `.forge/runner-state.json`, and `specs/` for
Anthropic-style API key patterns (`sk-ant-...`). Any match → 0/5.
Zero matches → 5/5. **Plain English:** "Have we leaked credentials into
build artefacts?" **Severity:** critical.

---

## Dimension 2 — Code  *(gating)*

Lint, types, coverage, complexity, hygiene. Eleven checks, all run against
production code only — `tests/`, `scripts/`, and `alembic/` are excluded
by `walk_production_files()` so fixtures, one-off scripts, and DDL-heavy
migration functions don't drown real regressions.

### 2.1 Zero lint errors

Runs `ruff check . --output-format=json`. 0 → 10/10, 1–5 → 7/10, 6–20 →
3/10, 20+ → 0/10. SKIP if ruff isn't installed. **Fix:** `ruff check . --fix`.

### 2.2 Zero type errors

Runs `mypy . --ignore-missing-imports --no-error-summary` and counts
`error:` lines. Same 0/5/20 thresholds as lint. SKIP if mypy missing.
**Fix:** add type hints, then `mypy .`.

### 2.3 Test coverage

Reads `coverage.json` (written by `pytest --cov=. --cov-report=json`).
≥80% → 15/15, 60–79 → 10/15, 40–59 → 5/15, <40 → 0/15. SKIP if the file is
absent. **Plain English:** "If something breaks, will our tests catch it?"

### 2.4 File modularity

Counts production `.py`/`.ts`/`.tsx` files over 300 and 500 lines. Zero
over either threshold → 10/10, zero over 500 → 7/10, ≤2 over 500 → 3/10,
>2 → 0/10. **Fix:** split files >500 lines.

### 2.5 Function size and complexity

AST walk over production Python. For each function counts its line span
and a coarse cyclomatic complexity (1 + If/For/While/Try/ExceptHandler/
BoolOp). Clean → 10/10, no >80-line and no cc>15 → 7/10, ≤2 violations →
3/10, otherwise 0/10. **Fix:** break large functions into helpers.

### 2.6 Naming quality

AST scan for generic store-context names (`data`, `result`, `temp`, `tmp`,
`foo`, `bar`, `test`, `x`, `val`, `item`) used as standalone variable or
function names. ≤2 → 5/5, ≤10 → 3/5, otherwise 0/5. The rule is
"descriptive label", not "no short names ever" — `nav_data` is fine,
bare `data` is not.

### 2.7 No dead code

Runs `ruff check . --select F401,F841` and counts findings. ≤3 → 5/5, ≤10
→ 3/5, otherwise 0/5. SKIP if ruff missing.

### 2.8 Error handling

Counts three problems: bare `except:` (×3), `except Exception:` not
followed by `log`/`raise` (×1), and `print(` calls inside `backend/`
(×1). 0 → 15/15, ≤3 → 10/15, ≤10 → 5/15, otherwise 0/15. **Fix:** narrow
excepts, log instead of print, use structlog. **Severity:** high if <10.

### 2.9 Consistent formatting

Runs `ruff format --check .`. Clean → 5/5, drift → 0/5. SKIP if ruff
missing. **Fix:** `ruff format .`.

### 2.10 API response consistency

Walks `backend/routes/**/*.py` and counts `response_model=` declarations
versus raw `return {` literals. response_models > 2× raw → 10/10, any
response_models → 7/10, otherwise 3/10. SKIP if `routes/` doesn't exist.

### 2.11 No TODO/FIXME markers

Greps `.py`/`.ts`/`.tsx` for `TODO|FIXME|HACK|XXX|WORKAROUND`. 0 → 5/5,
≤5 → 3/5, otherwise 0/5. **Fix:** convert markers to tracked issues.

---

## Dimension 3 — Architecture  *(gating)*

Heuristic structural checks, plus the doc-sync invariant. The original
spec called for a Claude-API architecture review; that is staged for V1.6
once the pgvector intelligence engine is wired. Until then, ten cheap
structural checks cover the same intent and run in <100ms.

### 3.1 Layered structure (routes/core/models/db)

Verifies `backend/{routes,core,models,db}` all exist. Pass → 20/20, fail →
5/20. **Fix:** create the missing folders. **Severity:** high.

### 3.2 Routes don't query JIP de_* tables directly

Greps `backend/routes/**/*.py` for `de_<word>` references. ATLAS may only
reach JIP data through `clients/jip_*.py` — the de_* tables are
read-only from JIP's side and the schema-fact table in CLAUDE.md exists
because direct access bit us in spec v2. Zero hits → 15/15, any → 0/15.
**Severity:** critical if violated.

### 3.3 JIP client abstraction present

Looks for any file under `backend/clients/` that mentions `/internal/`
plus an HTTP library (`httpx` or `requests`). Pass → 15/15. **Fix:** create
`backend/clients/jip_*.py` wrapping the JIP `/internal/` API.

### 3.4 Decimal not float

Greps every `backend/` Python file for `: float` annotations or `float(`
casts. Zero → 20/20, any → 0/20. Financial values are Decimal end-to-end.
**Severity:** critical if violated.

### 3.5 Structured logging

Verifies any project file imports `structlog`. Pass → 15/15. **Fix:**
swap `print()` and stdlib `logging` calls for `structlog.get_logger()` with
context kwargs.

### 3.6 Migrations via Alembic

`alembic.ini` exists at repo root → 15/15. **Fix:** `alembic init`.
Folded from the old DevOps dimension because schema drift is an
architectural concern, not infrastructure.

### 3.7 README present

`README.md` exists and is >500 chars → 10/10, otherwise 3/10. Folded from
the dropped Documentation dimension — a missing README is structural
debt, not a paperwork issue.

### 3.8 CLAUDE.md present and live

`CLAUDE.md` exists, >1000 chars, and contains the literal `ATLAS`
(i.e., it's project-specific, not a copy of the global rules) → 10/10,
otherwise 3/10. Folded from Documentation.

### 3.9 Architecture decisions recorded

Counts files under `docs/adr/*.md` and `## ` headings inside
`CLAUDE.md`. ≥3 ADRs OR ≥10 CLAUDE.md sections → 10/10, otherwise 5/10.
The OR clause exists because ATLAS records most decisions inline in
CLAUDE.md and the spec rather than as standalone ADRs.

### 3.10 Standards doc matches code

Runs `.quality/verify_doc_matches_code.py` and counts drift. The script
collects every `CheckResult("ID", "name", …)` from `checks.py` and
`dimensions/*.py` (including loop-driven tuple registrations) and every
`### <ID> <name>` heading in this file. Drift = checks missing in doc +
checks missing in code + name mismatches. Drift 0 → 10/10, otherwise →
0/10. This is the bidirectional invariant that keeps S2's promise. **Fix:**
add or rename the missing entries here in the same commit. **Severity:**
high if >0.

---

## Dimension 4 — API  *(gating)*

Live probe against the running backend at `ATLAS_API_BASE` (default
`http://127.0.0.1:8010`). C11 replaced the old SKIP-only stub. If `/health`
doesn't answer, every check after 4.1 returns `status="SKIP"` and the
dimension fails the gate — that's how the orchestrator catches dead
deploys (Step 3.5 smoke probe).

### 4.1 OpenAPI inventory

If the service is reachable, refreshes `backend/openapi.json` from
`/openapi.json`. Then checks the cached file exists and lists how many
paths it knows about. 5/5 if present, 0/5 if not.

### 4.2 Endpoint response time

Hits 8 representative GET endpoints (`/health`, `/api/v1/health`,
`/api/v1/ready`, `/api/v1/status`, `/api/v1/stocks/{sectors,breadth,
movers,universe}`) and computes p95 latency. <500ms → 15/15, <1s → 12/15,
<2s → 8/15, otherwise 4/15. **Severity:** high if <10.

### 4.3 Error rate

Counts non-2xx responses across the same 8 probes. 0 → 10/10, exactly 1 →
6/10, ≥2 → 0/10. **Severity:** critical if any non-2xx.

### 4.4 Response format compliance

For each 2xx response, validates `Content-Type: application/json` and
`json.loads` parses cleanly. All clean → 10/10, one short → 6/10,
otherwise 0/10.

### 4.5 DB query performance

Times the heaviest DB-backed endpoint, `/api/v1/stocks/universe`. <1s →
10/10, <2s → 7/10, <5s → 4/10, otherwise 0/10. This is a stand-in for the
EXPLAIN-ANALYZE work that lands in V1.6 with `pg_stat_statements`.

---

## Dimension 5 — Frontend  *(gating)*

C9 frontend hardening landed two cheap structural checks plus seven
SKIP-stubs that need a headless browser. The stubs run in the orchestrator
post-deploy chunk, not in the unit-test gate, so they SKIP here without
penalty.

### 5.0 Frontend present

If `frontend/` or `frontend/package.json` is absent, the dimension returns
a single failing check and bails. This stops the rest of the dim from
firing on a frontend-less repo.

### 5.1 Build succeeds

Looks for `frontend/.next/`. Pass → 10/10. The full `npm run build` runs
in the orchestrator deploy chunk — at gate time we're only verifying the
artifact exists. **Severity:** high if missing.

### 5.2 Bundle size

SKIP — requires `npm run build` + asset measurement. Lands in the
post-deploy chunk via the gstack skill.

### 5.3 Accessibility

SKIP — runs axe-core / pa11y in the headless browser chunk.

### 5.4 Mobile responsive

SKIP — needs viewport rendering at 375/768px.

### 5.5 Console errors

SKIP — needs a real Chromium load.

### 5.6 Component modularity

Walks `frontend/src/components/**/*.tsx` and counts files >200 lines. 0 →
10/10, any → 3/10. This is the only frontend check that runs without a
browser.

### 5.7 Loading states

SKIP — needs page-by-page interaction in the gstack chunk.

### 5.8 Indian locale

SKIP — requires DOM inspection of currency/percentage/date strings.

### 5.9 Design system

SKIP — requires visual diff against the JIP design tokens.

---

## Dimension 6 — Backend  *(informational until V1.6)*

The backend dimension scores the data plane: migrations, schema
correctness, dependency hygiene, and the daily intelligence pipeline. It
is **non-gating** today because four of its ten checks need objects that
don't exist yet (the daily pipeline, the live RDS connection in CI). When
V1.6 ships those, plan.yaml flips `gating=true` and the floor immediately
becomes 80% of `eligible`.

### b1 Alembic head matches models

Runs `alembic check`. Exit 0 → 10/10, drift → 0/10. SKIP if alembic
missing. **Plain English:** "Are DB migrations in sync with the SQLAlchemy
models?" **Fix:** `alembic revision --autogenerate -m "sync"; alembic
upgrade head`. **Severity:** high.

### b2 All FKs indexed

Connects via `DATABASE_URL` and queries `information_schema.table_constraints`
for every FK on `atlas_*` tables, then asks `pg_indexes` whether each FK
column has at least one index covering it. All covered → 10/10, any
unindexed → 0/10. SKIP if `DATABASE_URL` isn't set or the connection
fails. **Why this matters:** unindexed FK columns are the #1 cause of slow
JOINs in PostgreSQL, and ATLAS rolls 31 sectors × 2,743 stocks every
gate. **Fix:** add `index=True` to the SQLAlchemy column.

### b3 No float in financial columns

Same DB connection, queries `information_schema.columns` for any
`atlas_*` column with `data_type = 'double precision'`. None → 10/10, any
→ 0/10. **Plain English:** "The CLAUDE.md schema rules say money columns
are `Numeric(20,4)`, never `double precision` — does the live DB
agree?" **Severity:** critical if violated. The 3.4 architecture check
catches Python-side float; b3 catches the ground truth in PostgreSQL.

### b4 Docker build file present

`Dockerfile` exists at repo root → 10/10. ATLAS deploys the FastAPI
backend as a single container per service, so a missing Dockerfile means
the service can't ship.

### b5 Alembic configured

`alembic.ini` at repo root → 10/10. Distinct from b1 (which checks
*content*) and 3.6 (which checks the same file from the architecture
angle). The duplication is intentional: 3.6 fails the architecture gate
on missing config; b5 fails the backend gate on the same evidence so
backend stays self-contained when promoted.

### b6 pip-audit clean

Same audit as 1.3 but framed as a backend dependency-health check. 0
critical + 0 high → 10/10, 0 critical + ≤3 high → 7/10, otherwise 0/10.
SKIP if pip-audit missing. Kept in both dimensions because security
cares about exploitability and backend cares about library health — they
cite the same evidence but a future fork could specialize them.

### b7 Pipeline idempotent

If `backend/pipelines/daily.py` doesn't exist yet, the check returns
`max_score=0, eligible=0` and SKIPs — it doesn't penalize the dimension
during the V1.5 retrofit. Once the pipeline lands, V1.6 R3 wires a real
"run twice, compare row counts" probe and flips `max_score` to 10. **Plain
English:** "Can we re-run the daily pipeline without doubling the data?"

### b8 Intelligence writes on run

Same SKIP-on-missing pattern. V1.6 R3 will assert that running
`backend/pipelines/daily.py` produces ≥1 new row in `atlas_intelligence`,
proving the pgvector engine is wired to the orchestrator and not a
no-op. **Severity:** info today, high once promoted.

### b9 Decisions generated on run

Same shape. V1.6 R3 asserts that the daily run produces ≥1 row in
`atlas_decisions` whose `created_at` falls inside the run window —
i.e., the decision lifecycle system actually fires. Without this check, a
silently-broken decision generator would still let backend score green.

### b10 CI/CD workflows

`.github/workflows/*.yml` exists → 10/10. **Fix:** add
`.github/workflows/ci.yml`. Folded from the old DevOps dimension. Backend
owns "is CI alive" because backend owns "is the deploy reliable".

---

## Dimension 7 — Product  *(informational until V1.6 R1)*

Tracks the V1 completion criteria from `docs/specs/v1-criteria.yaml`.
S3 wired this dim to the real YAML: each criterion becomes one
`CheckResult`, dispatched via a declarative handler
(`http_contract`, `sql_count`, `sql_invariant`, `python_callable`,
`file_exists`). The dim stays `gating=false` — forge dashboard surfaces
it as a V1-completion progress bar so FMs can watch the score climb as
V1.6 chunks ship.

### How it works

1. Read `docs/specs/v1-criteria.yaml` + `v1-criteria.schema.json`.
2. Validate the top-level shape (cheap) and, if `jsonschema` is
   installed, the full schema.
3. For each criterion, dispatch by `check.type` to the handler in
   `.quality/dimensions/check_types/`. Each handler returns
   `(passed: bool, evidence: str)` — never raises.
4. Emit one `CheckResult` per criterion. 10/10 on pass, 0/10 on fail.
   Severity comes from the YAML; on pass it collapses to `info`.
5. V1.6 R1 flips `gating=true` once ≥13 of 15 criteria pass.

### Supported check types

- `http_contract` — GET URL, assert 200 under `max_latency_ms`.
- `sql_count` — scalar `COUNT(*)`, assert `min`/`max` bounds. Needs
  `ATLAS_DATABASE_URL` or `backend.config` + `psycopg2`.
- `sql_invariant` — scalar query, assert `equals`/`min`/`max`.
- `python_callable` — dotted path returning `(bool, str)`. Escape hatch
  for anything the declarative types can't express (AST scans,
  multi-endpoint checks, etc.).
- `file_exists` — path + optional `min_size_bytes`.

### p0 V1 criteria file

SKIP stub fired only when `docs/specs/v1-criteria.yaml` is missing or
malformed. Never fires on a healthy repo — if you see `p0`, the YAML
loader found something wrong with the criteria file.

### v1-01 /stocks/universe returns valid data matching contract
`http_contract` against `/api/v1/stocks/universe`, 2000ms budget.

### v1-02 /stocks/sectors returns 31 sectors with 22 metrics each
`python_callable` into `quality_product_checks.check_sectors_shape` —
asserts exactly 31 sectors and ≥22 metric columns per row (excluding
the `sector` label).

### v1-03 /stocks/{symbol} returns deep-dive for any stock
`http_contract` against `/api/v1/stocks/RELIANCE`, 500ms budget.

### v1-04 /query handles basic equity queries (filters + sort)
`python_callable` that POSTs `{filters: [], sort: [], limit: 1}` to
`/api/v1/query` and asserts 200.

### v1-05 Frontend: FM navigates Market → Sector → Stock flow
`python_callable` that file-checks the key pages/components
(`frontend/src/app/page.tsx`, `DeepDivePanel.tsx`). Not Playwright —
this is a presence gate, not a browser flow gate.

### v1-06 Deep-dive panel shows all conviction pillar data
`file_exists` on `frontend/src/components/DeepDivePanel.tsx` with a
500-byte floor (catches accidental stubs).

### v1-07 ≥5 decisions generated per pipeline run
`sql_count` on `atlas_decisions WHERE created_at >= now() - interval '1 day'`,
`min: 5`. **Expected to FAIL until V1.6 R1** — nothing writes decisions
yet.

### v1-08 FM can accept / ignore / override decisions
`python_callable` — asserts GET `/api/v1/decisions` returns 200 and
`backend/routes/decisions.py` exists. Liberal read of "accept/ignore/
override" — V1.6 R2 adds the lifecycle endpoints that make this
strict.

### v1-09 Sector rollup stock_count sums to ~2,700
`python_callable` that sums `stock_count` across `/sectors`. Tolerant
band (2300–2900) — §24.3 says "~2,700" as a ballpark, not a fixed
gate. Actual sum depends on NSE additions and corporate actions.

### v1-10 RS momentum present and numeric on deep-dive
`python_callable` — walks the `/stocks/RELIANCE` response for an
`rs_momentum` field and asserts it's numeric.

### v1-11 pct_above_200dma exposed on /sectors and in [0,100]
`python_callable` — every sector row must carry `pct_above_200dma` in
`[0, 100]`.

### v1-12 ≥10 intelligence findings stored after first pipeline run
`sql_count` on `atlas_intelligence WHERE created_at >= now() - interval '1 day'`,
`min: 10`. **Expected to FAIL until V1.6 R1** — intelligence engine
doesn't write yet.

### v1-13 Integration test suite present
`file_exists` on `tests/integration/test_v1_endpoints.py`, 500-byte
floor. The check 4.x api dim covers actual endpoint health; v1-13 is
the source-of-truth that the suite file itself exists.

### v1-14 No float in financial calculations
`python_callable` — regex-scans `backend/**/*.py` for `: float`
annotations. Mirrors architecture check 3.4 so the product dim stays
self-contained.

### v1-15 Response times: universe < 2s, deep-dive < 500ms
`python_callable` — hits both critical endpoints and asserts their
latency budgets in one check. Complements v1-01 + v1-03 by keeping
the two budgets paired in a single assertion.

### Worked example — criterion v1-07

§24.3 reads: *"Decisions generated: at least 5 decisions per pipeline
run"*. The YAML entry is:

```yaml
- id: v1-07
  title: "≥5 decisions generated per pipeline run"
  severity: critical
  source_spec_section: "§24.3"
  check:
    type: sql_count
    query: "SELECT COUNT(*) FROM atlas_decisions WHERE created_at >= now() - interval '1 day'"
    min: 5
```

On the current repo `atlas_decisions` is empty, so the handler returns
`(False, "count=0 < min=5")` and the check scores 0/10. Because
product is informational, this does not fail the gate — but it drops
the V1 completion progress bar on the forge dashboard from 100% toward
~86%. When the V1.6 R1 pipeline chunk lands and decisions start being
written, this check flips to pass automatically.

---

## Audit log — what changed in S3

- Product dim wired to real `docs/specs/v1-criteria.yaml` — 15 criteria,
  5 check types dispatched through `.quality/dimensions/check_types/`.
- `p1..pN` placeholder IDs replaced with `v1-01..v1-15` so the IDs are
  stable across slices (V2 criteria will use `v2-XX`).
- Forge dashboard now renders a V1 completion progress bar from the
  product dim score.
- Expected baseline on the current repo: 13/15 passing (86%). The two
  reliable failures are `v1-07` (no decisions written) and `v1-12`
  (no intelligence findings written). V1.6 R1 flips them green.

## Audit log — what changed in S2

S2 took the C1-era 53-check rubric, audited every entry against the S1
engine, and folded/dropped/added until each check on disk had exactly one
matching entry here. The fold/drop/add ledger lives in
[`CHANGES.md`](CHANGES.md). Highlights:

- **Composite formula deleted.** The old `Overall = Security×0.25 + …`
  block is gone. S1 made it meaningless.
- **DevOps and Documentation dimensions deleted.** High-value checks
  (Alembic, README, CLAUDE.md, ADR count, CI workflows, Dockerfile)
  folded into architecture and backend. Ceremony checks (SSL cert
  expiry, log rotation, RDS backup retention) dropped — they were
  manual and never automated.
- **Four-platforms framing deleted.** ATLAS is one platform, not a
  Command Center fleet.
- **"Fix with Claude" prompt templates deleted.** They duplicated the
  per-check `fix` field that every `CheckResult` already carries.
- **Backend dim documented for the first time** (b1–b10). The S1 file
  introduced these checks; S2 writes their plain-English rubric.
- **Product dim documented** with a worked example tied to V1 criterion 7.
- **3.10 Standards doc matches code** added — the new architecture check
  that runs `verify_doc_matches_code.py` and enforces this whole
  document's bidirectional contract.
