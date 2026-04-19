---
globs: ["*.py", "api/**", "app/**", "src/**/*.py"]
---
# Python backend conventions
- FastAPI with async endpoints. Use `async def` not `def` for route handlers
- Pydantic v2 models for all request/response schemas. Use `model_validator` not `validator`
- All query parameters: `Optional[type] = None` with explicit defaults. NEVER bare params
- Error responses: raise `HTTPException` with specific status codes, not generic 500
- Database: SQLAlchemy 2.0 async session. Use `async with session.begin():`
- All money/financial values: `Decimal` type, never `float`. Import from `decimal`
- Logging: `structlog` with context. Never `print()` in production
- Type hints on every function. Return types always specified
- Imports: stdlib first, third-party second, local third. Blank line separators
