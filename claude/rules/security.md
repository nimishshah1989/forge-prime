---
# No globs — always loaded for every file
---
# Security hard stops (non-negotiable)
- NEVER hardcode secrets, API keys, or passwords in source code
- NEVER use `allow_origins=["*"]` in production CORS configuration
- NEVER expose stack traces or internal error details to API responses
- ALWAYS validate input at system boundaries with Pydantic models
- ALWAYS use `Decimal` not `float` for financial calculations
- ALWAYS use parameterised SQL queries — never string interpolation
- ALWAYS add `index=True` on foreign key columns in SQLAlchemy models
- ALWAYS add `.env` and `*.pem` to `.gitignore` before first commit
- JWT secrets and DB passwords: environment variables only, never config files
- Dependencies: check `pip-audit` output before adding new packages
