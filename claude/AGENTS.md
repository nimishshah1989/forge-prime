# Forge Prime OS — Agents Layer

## Four Laws (non-negotiable)
1. **Prove, never claim** — run tests, show output, verify visually
2. **No synthetic data** — ever. No hardcoded mocks in production code
3. **Backend first always** — API working before any frontend touches it
4. **See what you build** — verify visually, check the browser, confirm the output

## Wiki
Before starting ANY task, read `~/.forge/prime/wiki/index.md`
Identify which patterns are relevant to THIS task's files and tech.
Read ONLY those specific articles. Do NOT read the entire wiki.
Wiki articles use Obsidian-flavored markdown: [[wikilinks]], YAML frontmatter.

## Role in the Forge
Gemini agents handle: PRD cross-validation, wiki compilation, visual verification,
quick single-file edits. Claude Code in the terminal handles: implementation,
code review, testing, shipping. Both follow the same Four Laws.

## Project conventions
- Financial values: Decimal, never float.
- Indian formatting: lakh/crore, not million/billion.
- Dates: IST timezone aware. Never naive datetime.
- API: FastAPI + Pydantic v2. DB: SQLAlchemy 2.0 async.
