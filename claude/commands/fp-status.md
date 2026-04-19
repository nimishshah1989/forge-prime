---
name: forge-status
description: Generate a project status dashboard. Shows chunk progress, bugs, tests, decisions, wiki stats. Creates an HTML file viewable in any browser.
---

Read the current project state and generate a status report.

## Data sources
- `tasks.json` — chunk statuses
- `docs/decisions/session-log.md` — decisions made
- `docs/specs/chunk-plan.md` — original plan
- `~/.forge/knowledge/wiki/index.md` — wiki stats
- Git log — recent commits

## Output
Create `docs/forge-dashboard.html` — self-contained HTML with:
1. Progress bar (chunks done/total)
2. Chunk cards (status, reviews, bugs, tests per chunk)
3. Decision timeline (chronological)
4. Wiki stats (articles, patterns, last compiled)
5. Active patterns relevant to this build
6. Knowledge graph visualization — read all [[wikilinks]] from wiki articles,
   render as an interactive D3 force-directed network graph. Nodes = articles,
   edges = wikilinks between them. Color nodes by category (bug-pattern=red,
   pattern=green, anti-pattern=amber, architecture=blue). Clicking a node
   shows the article summary. Include D3 via CDN in the HTML.

Style: white background, teal (#1D9E75) accents, professional. All CSS inline.
Mobile-viewable. D3 loaded from cdnjs CDN. Single self-contained file.

After creating: "Dashboard at docs/forge-dashboard.html"
