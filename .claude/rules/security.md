# Security

## File upload rules
- Only PDF files accepted (`allowed_file()` in `api/routes/analysis.py`)
- `werkzeug.utils.secure_filename()` always applied to uploaded filenames
- Files saved with `uuid4()` prefix to prevent collisions and path traversal
- PDF magic byte validation: file must start with `%PDF` (not just extension check)
- Hard upload limit: 50 MB (`MAX_CONTENT_LENGTH` in `api/config.py`)

## Session security
- Session IDs are `uuid.uuid4()` strings — never accept user-supplied session IDs as trusted
- Sessions auto-expire: 60 min (dev), 120 min (prod)
- All route handlers validate session existence before processing; return 404 if missing/expired
- Session state is in-memory only — lost on API restart (by design for local deployment)

## Input validation
- All required JSON fields checked at route entry; return 400 immediately if missing
- Bounding box inputs validated: integer types, no negatives, `x2 > x1`, `y2 > y1`
- Refer to `_validate_selection_bbox()` in `api/routes/analysis.py` for the pattern to follow

## Thread safety
- Audit log writes use a module-level `threading.Lock()` (`_FILE_LOCK` in `audit_logger.py`)
- All read-modify-write operations on JSON audit files must be inside this lock

## Documentation of Security Constraints
When implementing security-sensitive features:
1. Add inline comments in code explaining the security boundary (e.g., file upload validation, session checks)
2. Reference this file from code docstrings if a constraint is non-obvious: `/// See .claude/rules/security.md for file upload validation rules`
3. Do not expose detailed threat models in frontend docs; keep generic descriptions in `web/CostEstimator.Web/docs/`
4. High-risk workflows (file handling, session, input validation) should have corresponding test cases that document the defensive behavior

## Known limitations (local deployment only)
- No authentication or authorization — assumes trusted local network
- No HTTPS — HTTP only on localhost
- No rate limiting
- `SECRET_KEY` must be set via environment variable for any non-local use
- `.env` is not in `.gitignore` — never commit secrets to this file

## Do not introduce
- SQL queries built from string concatenation
- Shell commands constructed from user input (`subprocess` with `shell=True`)
- Unvalidated file paths derived from user input
- New file upload endpoints that skip the `secure_filename` + extension + magic-byte checks
- Undocumented security constraints in code (always add an explanatory comment and reference this file or `web/CostEstimator.Web/docs/`)
