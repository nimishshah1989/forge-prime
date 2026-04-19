# Project Constitution

## Four Laws (non-negotiable)
1. Prove, never claim — run tests, show output, verify visually
2. No synthetic data — ever. No hardcoded mocks in production code
3. Backend first always — API working before any frontend touches it
4. See what you build — check the browser, confirm the output

## Project Non-Negotiables
<!-- Add project-specific invariants below -->

## Tech Decisions
<!-- Record key architecture decisions: DB, framework, hosting, auth method -->

## Commit Protocol
- Only commit via `scripts/forge-ship.sh <CHUNK_ID> "summary"`
- Never raw `git commit`
- One chunk per session

## Financial Domain (if applicable)
- All monetary values: `Decimal` type, paise internally, rupees at API boundary
- Formatting: lakh/crore notation, ₹ symbol
- Dates: IST timezone-aware always
