---
name: testing-patterns
description: TDD patterns, pytest/Jest testing conventions, and test quality standards. Use when writing any tests.
auto_load: true
priority: high
---

# Testing Patterns Skill

## Trigger
When writing tests or implementing features that need tests.

## TDD Flow

1. **Red**: Write a failing test first
2. **Green**: Write minimal code to pass
3. **Refactor**: Clean up while tests stay green

## Test Structure (TypeScript/Jest)

```typescript
describe('ModuleName', () => {
  describe('functionName', () => {
    it('should do expected behavior when given input', () => {
      // Arrange
      const input = createTestInput();

      // Act
      const result = functionName(input);

      // Assert
      expect(result).toEqual(expectedOutput);
    });

    it('should throw when given invalid input', () => {
      expect(() => functionName(null)).toThrow();
    });
  });
});
```

## Test Structure (Python/pytest)

```python
class TestModuleName:
    """Tests for module_name."""

    async def test_expected_behavior(self):
        """Should do expected behavior when given input."""
        # Arrange
        input_data = create_test_input()

        # Act
        result = await function_name(input_data)

        # Assert
        assert result == expected_output

    async def test_raises_on_invalid_input(self):
        """Should raise ValueError when given invalid input."""
        with pytest.raises(ValueError):
            await function_name(None)
```

## Rules

### Naming
- Describe behavior, not implementation
- Good: `should return 404 when user not found` / `test_returns_none_for_missing_agent`
- Bad: `test getUserById` / `test_function`

### Isolation
- Each test is independent (no shared mutable state)
- Use `beforeEach`/setup fixtures for setup, not shared mutable state
- Clean up after tests (close connections, clear timers)

### Mocking
- Mock external dependencies (APIs, databases, file system)
- Don't mock the thing you're testing
- Use `jest.mock()` at module level, `jest.spyOn()` for specific methods (TS)
- Use `unittest.mock.AsyncMock` / `patch` for Python
- Reset mocks between tests

### What to Test
- Happy path (expected input -> expected output)
- Error cases (invalid input, missing data, network failures)
- Edge cases (empty arrays, null values, boundary conditions)
- Integration points (API endpoints with supertest/httpx)

### What NOT to Test
- Third-party library internals
- Type checking (the compiler/mypy does this)
- Simple getters/setters with no logic

### Anti-Patterns to Avoid
- No `waitForTimeout()` or `sleep()` in tests
- No hardcoded test IDs that depend on database state
- No tests that depend on execution order
- No `any` type assertions to make tests pass

## Python Integration Test Pattern

**NEVER use bare `pytest.skip()` at the top of a test function.** This makes the test unreachable via `pytest -m integration` and leaves functionality unverified.

```python
# ❌ BAD: Unreachable via pytest -m integration
async def test_database_integration():
    pytest.skip("Requires database")
    ...

# ✅ GOOD: Skips conditionally, runs when services available
import os
import pytest

@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="Requires DATABASE_URL environment variable"
)
async def test_database_integration():
    ...
```

## Python Linting Before Commit

Always run `ruff check` and `ruff format --check` on Python code before committing. Common violations that waste retry cycles:
- `datetime.timezone.utc` → use `datetime.UTC` (Python 3.12+)
- Missing `strict=True` on `zip()` calls
- Unsorted imports (stdlib → third-party → local)
- Unused imports
- Ambiguous variable names (`l`, `O`, `I`)
