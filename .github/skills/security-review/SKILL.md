---
name: security-review
description: Use when reviewing code for security vulnerabilities or before deploying sensitive changes. Covers OWASP Top 10 adapted for Python codebases.
---

# Security Review

Systematic security review focused on Python applications. Use before merging code that handles user input, authentication, data access, or external integrations.

## When to Use

- Before deploying code that handles sensitive data
- When adding authentication or authorization logic
- When processing user-supplied input
- When integrating external APIs or services
- When changing database queries or file operations
- During periodic security audits

## OWASP Top 10 — Python-Focused Checklist

### 1. Injection

**What:** Untrusted data sent to an interpreter as part of a command or query.

| Risk | Pattern | Mitigation |
|------|---------|------------|
| SQL injection | String formatting in queries: `f"SELECT * FROM users WHERE id = {user_id}"` | Use parameterized queries: `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))` |
| Command injection | `os.system(f"convert {filename}")`, `subprocess.call(cmd, shell=True)` | Use `subprocess.run(["convert", filename], shell=False)` with list args |
| Code injection | `eval(user_input)`, `exec(user_input)` | Never eval untrusted input. Use `ast.literal_eval()` for data parsing |
| Template injection | `render_template_string(user_input)` | Use `render_template()` with separate template files |

### 2. Broken Authentication

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Hardcoded credentials | `password = "admin123"` in source | Use environment variables or secrets manager |
| Weak token generation | `random.randint()` for tokens | Use `secrets.token_urlsafe()` or `secrets.token_hex()` |
| Missing rate limiting | Login endpoint without attempt throttling | Add rate limiting (e.g., `flask-limiter`) |
| Plain-text passwords | Storing passwords without hashing | Use `bcrypt` or `argon2-cffi` |

### 3. Sensitive Data Exposure

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Logging secrets | `logger.info(f"Request: {request.headers}")` | Sanitize logs, never log auth headers or tokens |
| API keys in code | `API_KEY = "sk-..."` | Use `.env` files + `python-dotenv`, never commit secrets |
| Error details leaked | Returning full tracebacks to clients | Return generic error messages; log details server-side |
| Unencrypted storage | Storing PII in plain text files | Encrypt at rest, use proper database with access controls |

### 4. Broken Access Control

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Missing auth checks | Endpoints accessible without login | Add `@login_required` or equivalent decorators |
| IDOR | `GET /api/users/{id}` without ownership check | Verify requesting user owns or has permission to access resource |
| Path traversal | `open(f"uploads/{user_filename}")` | Validate and sanitize paths: `os.path.basename()`, check against allowed directory |
| Privilege escalation | Role checks only on frontend | Enforce authorization server-side on every request |

### 5. Security Misconfiguration

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Debug mode in prod | `app.run(debug=True)` | Use environment-based config: `debug=os.getenv("DEBUG", "false") == "true"` |
| CORS wildcard | `CORS(app, origins="*")` | Restrict to specific allowed origins |
| Default secrets | `SECRET_KEY = "changeme"` | Generate strong random keys per environment |
| Verbose errors | `PROPAGATE_EXCEPTIONS = True` in production | Disable in production, use structured error handling |

### 6. Vulnerable Components

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Outdated packages | Known CVEs in pinned versions | Run `pip-audit` or `safety check` regularly |
| Unpinned dependencies | `requests` without version in requirements.txt | Pin exact versions: `requests==2.31.0` |
| Unused dependencies | Packages in requirements.txt not used in code | Audit and remove unused packages |

### 7. Unsafe Deserialization

| Risk | Pattern | Mitigation |
|------|---------|------------|
| Pickle from untrusted source | `pickle.loads(user_data)` | Use JSON for untrusted data. If pickle required, use `hmac` to verify integrity |
| YAML unsafe load | `yaml.load(data)` | Use `yaml.safe_load(data)` |
| Arbitrary object creation | Custom deserializers that instantiate classes from input | Whitelist allowed types |

### 8. Insufficient Logging & Monitoring

| Risk | Pattern | Mitigation |
|------|---------|------------|
| No auth event logging | Login successes/failures not logged | Log all authentication events with timestamps |
| No anomaly detection | Unusual patterns go unnoticed | Monitor for repeated failures, unusual access patterns |
| Sensitive data in logs | Passwords, tokens in log output | Implement log sanitization |

### 9. Server-Side Request Forgery (SSRF)

| Risk | Pattern | Mitigation |
|------|---------|------------|
| User-controlled URLs | `requests.get(user_provided_url)` | Validate URL against allowlist of domains/IPs |
| Internal network access | Fetching metadata endpoints | Block requests to private IP ranges (10.x, 172.16.x, 192.168.x, 169.254.x) |
| Redirect following | Auto-following redirects to internal resources | Disable redirects or validate each hop |

### 10. Insecure Design

| Risk | Pattern | Mitigation |
|------|---------|------------|
| No input size limits | Processing arbitrarily large uploads | Set `MAX_CONTENT_LENGTH` and validate file sizes |
| Missing business logic validation | Negative quantities, future dates where invalid | Validate business rules, not just types |
| Race conditions | Check-then-act without locking | Use database transactions, file locks, or atomic operations |

## Review Process

1. **Scope** — Identify which OWASP categories apply to the code being reviewed
2. **Scan** — Walk through the checklist for applicable categories
3. **Classify** — Rate each finding: CRITICAL / HIGH / MEDIUM / LOW
4. **Report** — Use the summary format below
5. **Verify** — Confirm fixes address root cause, not just symptoms

## Security Review Summary Format

```markdown
## Security Review: [Component Name]

### Scope
Categories reviewed: Injection, Auth, Access Control

### Findings

| # | Category | Severity | Description | Location |
|---|----------|----------|-------------|----------|
| 1 | Injection | 🔴 CRITICAL | SQL query built with f-string | api/routes.py:45 |
| 2 | Auth | 🟠 HIGH | No rate limiting on login | api/auth.py:12 |
| 3 | Config | 🟡 MEDIUM | Debug mode not env-gated | app.py:8 |

### Verdict
❌ **Block merge** — 1 CRITICAL finding must be resolved.

### Recommended Actions
1. Replace f-string SQL with parameterized query
2. Add flask-limiter to login endpoint
3. Gate debug mode on environment variable
```

## Quick Reference: Python Security Patterns

```python
# ❌ DANGEROUS
cursor.execute(f"SELECT * FROM users WHERE email = '{email}'")
os.system(f"convert {filename}")
pickle.loads(untrusted_data)
yaml.load(data)
eval(user_input)
open(f"data/{user_path}")

# ✅ SAFE
cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
subprocess.run(["convert", filename], shell=False)
json.loads(untrusted_data)
yaml.safe_load(data)
ast.literal_eval(data_string)
safe_path = os.path.join("data", os.path.basename(user_path))
```
