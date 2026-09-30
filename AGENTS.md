# Agent Guide for hb-backend

This file orients agentic coding tools to the project conventions and workflows.
Keep guidance aligned with existing code and avoid introducing new patterns
unless clearly justified.

## Repository overview

- Stack: FastAPI + MongoDB (Motor + PyMongo/GridFS)
- Entry point: `app/main.py`
- Settings: `app/core/config.py` (Pydantic Settings, `.env`)
- Routers: `app/routers/**`
- Repositories (DB access): `app/repos/**`
- Services (external providers): `app/services/**`
- Utilities: `app/utils/**`

## Cursor/Copilot rules

- Cursor rules: none found in `.cursor/rules/` or `.cursorrules`.
- Copilot rules: none found in `.github/copilot-instructions.md`.

If these files are added later, mirror their instructions here.

## Build, lint, test commands

No dedicated build/lint/test scripts are defined in this repo.
Use the commands below as the current source of truth.

### Environment setup

- Create venv: `python -m venv .venv`
- Activate (Windows): `.venv\Scripts\activate`
- Activate (bash): `source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Configure env: `cp .env.example .env` (if `.env.example` exists)

### Run the API locally

- `uvicorn app.main:app --reload --port 8000`

### Lint/format

- No formatter/linter is configured.
- If you add one, keep it in AGENTS.md and be explicit about the command.

### Tests

- No test suite or test files are currently present.
- If tests are added later, prefer `pytest`.

Run all tests (if/when added):

- `pytest`

Run a single test file (if/when added):

- `pytest path/to/test_file.py`

Run a single test case or function (if/when added):

- `pytest path/to/test_file.py::TestClass::test_name`
- `pytest path/to/test_file.py::test_name`

Run by keyword match (if/when added):

- `pytest -k "keyword"`

## Code style and conventions

These guidelines reflect current code patterns and should be followed unless
you are intentionally refactoring to a new standard.

### Python version and typing

- Use Python 3.10+ style typing (e.g., `str | None`, `list[dict]`).
- Prefer explicit type hints on public helpers and repo methods.
- Keep runtime types simple; use Pydantic for request validation.

### Imports

- Group imports as: standard library, third-party, local `app.*`.
- Use absolute imports within the project (e.g., `from app.core...`).
- Avoid unused or duplicate imports; keep modules tidy.

### Formatting

- 4-space indentation, no tabs.
- Keep lines reasonably short; break long argument lists over lines.
- Use trailing commas on multi-line dicts and function calls when helpful.
- Avoid excessive inline comments; comment only for non-obvious logic.

### Naming

- Modules, functions, variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE` (e.g., `ALLOWED_ORIGINS`).
- Router instances are named `router` and defined at module top.

### API layer (FastAPI)

- Use `APIRouter` with `prefix` and `tags` defined per module.
- Endpoints are async and return dicts (FastAPI handles JSON serialization).
- Dependencies injected with `Depends` in function signatures.
- Auth guards are composed via `require_roles` and `get_current_user`.

### Request/response models

- Use Pydantic `BaseModel` for request bodies where validation is needed.
- CamelCase input fields are used to match frontend payloads
  (e.g., `dateOfBirth`, `confirmPassword`).
- Normalize to `snake_case` when storing in MongoDB
  (e.g., `date_of_birth`, `full_name`).

### Error handling

- Use `http_error(status, code, message)` to raise errors.
- Errors serialize to `{ "error": { "code": ..., "message": ... } }`.
- Prefer explicit error codes such as `AUTH_REQUIRED`, `INVALID_TOKEN`.
- Keep validation errors consistent with existing responses.

### Date and time

- Use timezone-aware UTC timestamps: `datetime.now(timezone.utc)`.
- For display strings, use `isoformat()`.

### Database access (MongoDB)

- Use `app.core.db.get_db()` and repo classes for DB operations.
- Repos encapsulate MongoDB access; routers should not talk to collections.
- Convert ObjectId to string with `app.utils.bson.str_id` for responses.
- Parse user-supplied ids with `app.utils.bson.oid`.
- Favor `insert_one`, `find_one`, `update_one`, `delete_one` patterns.

### Repository pattern

- One repo per domain collection (e.g., `UsersRepo`, `DoctorsRepo`).
- Repo methods are async and return raw or transformed documents.
- Repos are dependency-injected with `Depends`.

### Services

- External integrations live in `app/services/**`.
- Keep providers stateless and pure where possible.
- Verify third-party webhook signatures before processing events.

### Utilities

- Small shared helpers live in `app/utils/**`.
- Keep helpers side-effect free and easy to test.

### Response shape conventions

- Lists usually return `{ "data": [...], "meta": {...} }`.
- Paginated responses include `total`, `page`, `page_size`, `has_more`.
- Single entities are often nested under a domain key (e.g., `"doctor"`).

### Security/auth

- Access/refresh tokens are JWTs created in `app/core/security.py`.
- `ACCESS_TOKEN_MINUTES` and `REFRESH_TOKEN_DAYS` come from settings.
- Normalize emails to lowercase and trim whitespace.
- Passwords are hashed with bcrypt; long passwords are pre-hashed.

### Configuration

- Settings in `app/core/config.py` read from `.env` via Pydantic.
- Unknown env vars are ignored (`extra="ignore"`).
- Do not hardcode secrets; use settings fields instead.

### File and module organization

- New routes go in `app/routers/` with a matching repo in `app/repos/`.
- Admin endpoints live under `app/routers/admin/`.
- Avoid circular imports; keep core utilities minimal.

## Practical guidance for agents

- Inspect existing patterns before introducing new structure.
- Prefer extending repos rather than direct DB access in routers.
- Keep response formats backward compatible when editing endpoints.
- When in doubt, match current API shapes instead of inventing new ones.

## Known gaps

- No automated linting or tests are configured.
- Add commands here if tooling is introduced.
