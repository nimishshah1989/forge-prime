# Forge Prime Conductor

You are in a fresh session. One chunk. Build it. Ship it. Done.

## Boot (always first)
1. Read CLAUDE.md
2. Read .forge/constitution.md
3. Read ~/.forge/prime/wiki/index.md — find 1-2 relevant articles only
4. Read docs/specs/chunks/{chunk_id}.md

## Execute
1. Implement the punch list
2. pytest tests/ -v --tb=short (or npm test for frontend)
3. python .quality/engine.py --gate
4. scripts/forge-ship.sh {chunk_id} "summary"
   (Codex adversarial review runs inside forge-ship.sh)
5. sqlite3 orchestrator/state.db "SELECT status FROM chunks WHERE id='{chunk_id}'"
   Must return DONE.

## Hard stops → log BUILD_STATUS.md, exit non-zero
- float in financial calculation
- raw git commit bypassing forge-ship.sh
- writing to de_* table
- non-deterministic test result

CURRENT CHUNK: {chunk_id}
