# OSHO WISDOM ENGINE — Completion Specification
# This is the validation project for Forge Prime
# Run AFTER forge-prime is built and `forge doctor` is green

## Purpose

This project proves forge-prime works end-to-end. Forge Prime will be used
to complete the Osho Wisdom Engine to a fully working, production-deployed
state. Every chunk will run through forge-prime's full pipeline including
quality gates, wiki learning, model routing, and dashboard visibility.

---

## Current State (as of 2026-04-19)

### What works
- Backend: FastAPI on EC2 (13.206.34.214:8000), ChromaDB with 1.3M paragraphs
  already embedded and indexed, SQLite DB with events + paragraphs tables
- Frontend: Next.js on Vercel (https://osho-zeta.vercel.app)
- Basic "Ask Osho" page: text input → SSE streaming → response renders
- Map page: tree view (Year → Series → Talk) from hierarchy API
- Data files: constellation_data.json (1.2MB), nebula_data.json (2MB)
  already pre-computed and in public/
- Three.js + @react-three/fiber already in package.json

### What is broken / missing
1. References feature: backend returns book/title metadata in search results
   but frontend has no way to show/hide them
2. Nebula visualization: nebula_data.json exists but is not rendered as
   an interactive WebGL experience — ConstellationMap.tsx is a stub
3. Page routing: two separate experiences (Ask + Map/Nebula) exist as
   separate routes but have no coherent navigation
4. No search-to-visual connection: clicking a nebula node should
   trigger a search and show related content

### Known issues
- jsl-wealth-key.pem is committed to the repo — REMOVE IMMEDIATELY
- Cloud API URL is hardcoded: http://13.206.34.214:8000 — needs env var
- No error boundaries on streaming components
- ConstellationMap.tsx renders nothing useful currently
- CORS on backend allows all origins

---

## What Needs to Be Built

### Feature 1: Ask Osho with References Toggle

**The experience:**
User types a question. Gets a streaming response. A checkbox at the
top: "Show Sources". When checked, after the main response, a structured
citations section appears showing the books and discourse titles that
were retrieved to form the answer.

**Backend changes needed:**
The `/stream` endpoint currently streams raw text. It needs to also
stream structured citation data. Approach: stream the wisdom text first,
then emit a special marker `[CITATIONS_START]`, then stream JSON citations,
then `[CITATIONS_END]`. Frontend parses this.

Alternative: add `/stream-with-refs` endpoint that returns SSE events
in two types: `event: wisdom` (text chunks) and `event: citation`
(one JSON citation object per source). Frontend listens to event type.

Use the SSE event-type approach — it's cleaner.

**Frontend changes needed:**
- Add "Show Sources" checkbox (default: off, persists in localStorage)
- When streaming, listen for `event: wisdom` and `event: citation`
- Wisdom chunks: append to response display as before
- Citation events: collect into a citations list
- After streaming ends: if "Show Sources" is on, show the citations panel
  under the response with book title, discourse title, date, location

**Citation display format:**
```
─────────────────────────────────────────────
Sources from this synthesis
─────────────────────────────────────────────
The Mustard Seed · Series: The Gospel of Thomas · 1974 · Poona
The Book of Secrets · Series: Vigyan Bhairav Tantra · 1973 · Bombay
Tantra: The Supreme Understanding · 1975 · Poona
```

Minimal, elegant, matches the existing black/gold/ivory aesthetic.

**Quality gates for this feature:**
- Backend: pytest tests/test_stream_refs.py (SSE event parsing test)
- Frontend: TypeScript strict clean
- No extra latency: citations should not slow down the wisdom stream

---

### Feature 2: The Nebula — Interactive Wisdom Constellation

**The vision (from Nimish):**
A full-screen immersive visualization of 1.3M paragraphs' worth of Osho
content organized into a nebula. Not a cool-looking feature — an actual
navigation and understanding tool. Multiple "lenses" to explore the content:
by teaching theme, by era, by location, by concept cluster.

**What you have to work with:**
- nebula_data.json (2MB): already pre-clustered. Check its structure.
- constellation_data.json (1.2MB): a second clustering. Check its structure.
- Three.js + @react-three/fiber: already installed
- ConstellationMap.tsx: exists but is currently a stub/placeholder

**Step 1: Understand the data**
Before building anything, read both JSON files and understand:
- What are the clusters? How many? What do they represent?
- What are the data points within each cluster?
- What metadata exists per point (book title, topic, date, location)?

Then decide: which JSON file is more suitable for the nebula visualization?
Use the richer one.

**Step 2: The Nebula visualization**

The nebula page replaces the current placeholder on `/` or becomes the
main page, with Ask Osho moving to a panel within it.

Visual design:
- Full-screen canvas, black background, star-field feel
- Each major cluster = a glowing nebula cloud (different color per theme)
- Individual data points = tiny particles within each cloud
- Camera starts zoomed out showing all clusters as colored nebulae
- Hover over cluster: label appears showing the theme name
- Click cluster: zoom in smoothly, particles spread apart, each becomes
  an individual discourse point
- Hover particle: tooltip shows book title + location + date
- Click particle: opens a side panel with that discourse passage + Ask Osho
  pre-loaded with context from that specific passage

**Lenses (the "creative representation" Nimish asked for):**
A small lens switcher in the top-right. Four lenses:
1. **Themes** (default): clusters by teaching topic (meditation, love, death,
   consciousness, society, politics, religion, enlightenment, etc.)
2. **Timeline**: clusters by era (Bombay years 60s, Poona 1 70s,
   Rajneeshpuram 80s, Poona 2 late 80s-90s)
3. **Geography**: clusters by location (Pune, Bombay, Oregon, Kathmandu, etc.)
4. **Concepts**: AI-derived semantic clusters (what is actually being discussed)

Each lens re-arranges the same particles into different cluster formations
with a smooth transition animation.

**Connection to search:**
When user types in Ask Osho and gets a response, the nebula should
highlight (glow brighter) the clusters and individual points that were
retrieved to form that answer. This creates a visual map of "where in
Osho's body of work this answer comes from."

**Backend changes needed for nebula:**
- Add `/api/cluster-metadata` endpoint: returns cluster names, sizes,
  color assignments per lens type
- Add `/api/particle/{id}` endpoint: returns full paragraph content +
  surrounding context for a specific point
- Modify `/stream` to also return the retrieved paragraph IDs so frontend
  can highlight them in the nebula

**Performance requirement:**
With 1.3M paragraphs, full rendering is impossible. Strategy:
- Render cluster centroids and approximate cloud shapes always (~500 points)
- On zoom-in to a cluster: load that cluster's actual points (~1000-5000)
- Use instanced mesh rendering (Three.js InstancedMesh) for particles
- Target: 60fps on modern laptop, 30fps minimum

**If nebula_data.json is not rich enough:**
Generate better clustering data using the backend. Add a
`/api/clusters?lens=themes&limit=20` endpoint that queries ChromaDB
and SQLite to generate meaningful clusters. This is preferable to using
pre-computed JSON that may not have the right structure.

---

### Feature 3: Navigation + Page Architecture

Currently:
- `/` = Ask Osho (just the search input)
- `/map` = Tree view (Year → Series → Talk)

After completion:
- `/` = Nebula (full-screen, immersive, the main experience)
- `/ask` = Ask Osho (clean, focused)
- `/map` = Mind Map tree (keep existing, improve it)

Navigation: three icons in top-right corner:
- Nebula icon → `/`
- Chat icon → `/ask`
- Map icon → `/map`

The three experiences are connected: content found in nebula can be
asked about in ask, references in ask can be explored in map.

---

### Feature 4: Production Hardening

Fix all the issues that exist before calling this done:

1. **Remove committed PEM key** (jsl-wealth-key.pem — CRITICAL):
   ```bash
   git rm jsl-wealth-key.pem
   git filter-repo --invert-paths --path jsl-wealth-key.pem
   # or use BFG Repo Cleaner
   ```

2. **Env var for backend URL**:
   `NEXT_PUBLIC_API_URL` in Vercel env vars, not hardcoded in route.ts

3. **CORS fix on backend**:
   Replace `allow_origins=["*"]` with `["https://osho-zeta.vercel.app"]`

4. **Error boundaries**:
   Wrap the streaming component in an error boundary. Show "The stillness
   remains undisturbed" message on error, not a white crash screen.

5. **Rate limit UX**:
   Currently returns raw error text. Show a clean "Free tier is resting,
   please wait 60 seconds" message with a countdown timer.

---

## Forge Prime Plan (plan.yaml for this project)

```yaml
version: "1.0"
name: "Osho Wisdom Engine — V2 Completion"

settings:
  repo_root: /home/ubuntu/osho   # EC2 path
  default_model: sonnet
  quality:
    domain: general
    project_type: fastapi_next
    gating_dims: [security, code, frontend]
  post_chunk:
    enabled: true
    script: scripts/post-chunk.sh

chunks:
  - id: O1
    title: "Production hardening: remove PEM, fix CORS, env vars"
    model: sonnet
    status: PENDING
    punch_list:
      - "jsl-wealth-key.pem removed from git history"
      - "NEXT_PUBLIC_API_URL in env, not hardcoded"
      - "CORS allows only vercel domain"
      - "TypeScript strict clean"

  - id: O2
    title: "Backend: SSE event-type streaming with citations"
    model: sonnet
    status: PENDING
    depends_on: [O1]
    punch_list:
      - "POST /stream emits event:wisdom and event:citation SSE types"
      - "pytest tests/test_stream_events.py green (wisdom chunks arrive, citations arrive)"
      - "Latency to first token unchanged (<300ms)"

  - id: O3
    title: "Frontend: Ask Osho with references toggle"
    model: sonnet
    status: PENDING
    depends_on: [O2]
    punch_list:
      - "Show Sources checkbox visible, persists in localStorage"
      - "When checked: citations panel renders below response"
      - "When unchecked: no citations shown (default)"
      - "TypeScript strict clean, npm run build succeeds"
      - "Vercel deployment green"

  - id: O4
    title: "Backend: cluster metadata + particle detail endpoints"
    model: sonnet
    status: PENDING
    depends_on: [O1]
    punch_list:
      - "GET /api/clusters?lens=themes returns top 20 clusters with name, size, color"
      - "GET /api/particle/{id} returns paragraph content + context"
      - "POST /stream modified to also return retrieved_paragraph_ids in citation event"
      - "pytest tests/test_cluster_api.py green"

  - id: O5
    title: "Nebula visualization: core Three.js instanced particle renderer"
    model: opus
    status: PENDING
    depends_on: [O4]
    punch_list:
      - "Full-screen canvas renders cluster clouds as colored particle groups"
      - "60fps on target hardware"
      - "Camera zoom in/out smooth"
      - "Hover on cluster: label shows theme name"
      - "npm run build succeeds, no TypeScript errors"

  - id: O6
    title: "Nebula: lens switching + click-to-zoom + particle detail"
    model: sonnet
    status: PENDING
    depends_on: [O5]
    punch_list:
      - "Four lens switcher (Themes/Timeline/Geography/Concepts)"
      - "Smooth transition animation between lens arrangements"
      - "Click cluster: zoom in, particles spread"
      - "Click particle: side panel shows passage + Ask Osho link"

  - id: O7
    title: "Search-to-nebula connection: highlight retrieved passages"
    model: sonnet
    status: PENDING
    depends_on: [O3, O6]
    punch_list:
      - "After Ask Osho response: retrieved passage IDs highlighted in nebula"
      - "Highlighted particles glow brighter with pulse animation"
      - "Connection line from search input to highlighted cluster (subtle)"

  - id: O8
    title: "Navigation + page architecture + final UI polish"
    model: sonnet
    status: PENDING
    depends_on: [O7]
    punch_list:
      - "Three-page architecture: / (nebula), /ask, /map"
      - "Navigation icons in top-right"
      - "Mobile responsive (375px viewport test)"
      - "Lighthouse performance score ≥80"
      - "Vercel build and deployment green"
      - "Live URL at https://osho-zeta.vercel.app works end-to-end"
```

---

## How to Run This Through Forge Prime

```bash
# 1. Initialize forge-prime on the Osho project
cd /home/ubuntu/osho
forge init osho-wisdom-engine

# 2. Copy the plan above into orchestrator/plan.yaml

# 3. Start the autonomous build
forge run

# 4. Watch the dashboard
# Open http://13.206.34.214:8099 in browser
# See each chunk progress in real time

# 5. If a chunk gets stuck
forge run --retry O5  # re-run specific chunk

# 6. Check final state
forge status
# Should show: all 8 chunks DONE

# 7. Verify live
# https://osho-zeta.vercel.app — Ask Osho with references
# https://osho-zeta.vercel.app — Nebula visualization
```

---

## Definition of "Proof That Forge Prime Works"

The Osho project is PROVEN when ALL of the following are true:

1. `forge doctor` shows all green on the machine running forge-prime
2. Dashboard at http://13.206.34.214:8099 shows all 8 Osho chunks DONE
3. Dashboard shows: tokens used per chunk, model used per chunk,
   tests passed per chunk, quality gate scores per chunk
4. Wiki has at least 6 articles created from the 8 chunk sessions
5. https://osho-zeta.vercel.app loads and works
6. Typing "What is meditation?" → streaming response → bibliography shown when "Show Sources" checked
7. Nebula loads, shows colored clusters, can zoom in, hover shows titles
8. Nebula highlights passage clusters after an Ask Osho search
9. jsl-wealth-key.pem is NOT in the git history
10. `git log origin/main..HEAD` on the EC2 osho repo returns empty (fully pushed)

If all 10 are true, forge-prime is proven.

---

## IMPORTANT: Security Priority

Before running ANY chunk, manually:
```bash
cd /home/ubuntu/osho
pip install bfg  # or download BFG jar
java -jar bfg.jar --delete-files jsl-wealth-key.pem
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

This must happen before forge-prime touches the repo. The PEM key exposure
is a critical security issue regardless of the rest of the build.
