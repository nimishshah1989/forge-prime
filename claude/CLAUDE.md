# Forge Prime OS

## Four Laws (non-negotiable)
1. **Prove, never claim** — run tests, show output, verify visually
2. **No synthetic data** — ever. No hardcoded mocks in production code
3. **Backend first always** — API working before any frontend touches it
4. **See what you build** — check the browser, confirm the output

## Wiki
Before ANY implementation: read `~/.forge/prime/wiki/index.md`
Identify relevant articles. Read ONLY those (1-2 max). Not end-to-end.

## Conventions
- Tests: pytest (backend) + npm test (frontend). 100% of declared tests must pass.
- Commit only via `scripts/forge-ship.sh`. Never raw git commit.
- One chunk per session. Fresh context per chunk.
- Subagents: `context: fork` always. Main agent sees summaries only.
- Financial values: Decimal, never float.
- Dates: IST timezone-aware always.

## Commands
/fp-build — conductor: PRD → plan → implement loop
/fp-compile — wiki compile
/fp-status — project status dashboard
/fp-quick — small task workflow
