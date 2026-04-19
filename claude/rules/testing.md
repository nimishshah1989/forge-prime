---
globs: ["tests/**", "*.test.*", "*.spec.*", "test_*.py", "*_test.py"]
---
# Testing conventions
- Every bug fix must have a regression test that fails before the fix
- Test naming: `test_<what>_<condition>_<expected>` (e.g., `test_login_bad_password_returns_401`)
- 80% line coverage minimum on `services/` and core business logic
- Use `factory_boy` for model factories — never hardcoded fixture data
- Never mock the system under test (SUT). Mock external dependencies only
- Integration tests: mark with `@pytest.mark.integration` so CI can skip them
- Async tests: use `pytest-asyncio` with `@pytest.mark.asyncio`
- No `time.sleep()` in tests — use mocks or proper async fixtures
- Frontend: `npm test` must pass before shipping
- Flaky tests must be fixed or deleted — never `@pytest.mark.skip` without a ticket
