---
globs: ["**/models/**", "**/migrations/**", "**/schemas/**", "alembic/**"]
---
# Database conventions
- SQLAlchemy 2.0 with mapped_column() syntax. Not legacy Column()
- Every foreign key column MUST have `index=True`. No exceptions
- Every table MUST have: id (UUID), created_at (tz-aware), updated_at (tz-aware)
- Money columns: `Numeric(precision=20, scale=4)`. Never Float
- Use Alembic for ALL schema changes. Never raw SQL DDL
- Soft delete: `is_deleted Boolean default False` + `deleted_at DateTime nullable`
- Enum columns: Python Enum class + SQLAlchemy Enum type. Never raw strings
- Relationships: always specify `lazy="selectin"` or explicit joinedload. Never N+1
- Connection pooling: `pool_size=5, max_overflow=10, pool_pre_ping=True`
