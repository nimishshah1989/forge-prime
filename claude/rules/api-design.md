---
globs: ["**/routes/**", "app/api/**", "backend/routes/**", "**/routers/**"]
---
# API design conventions
- All route handlers must be `async def`
- Request/response: Pydantic v2 models always. No bare dicts at boundary
- Errors: `HTTPException` with specific status codes. Never generic 500
- Response envelope: `{"data": ..., "_meta": {"request_id": ...}}`
- No SQL in route handlers — delegate to service layer
- Context: `structlog.contextvars.bind_contextvars(request_id=...)` at entry
- CORS: explicit origins only. Never `allow_origins=["*"]` in production
- Rate limiting required on all public (unauthenticated) endpoints
- Run `python scripts/check-api-standard.py` after any route change
- OpenAPI descriptions required on all path operations
