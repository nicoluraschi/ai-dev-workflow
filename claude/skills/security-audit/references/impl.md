## PHASE 3: IMPL — Code Security Audit

**Goal:** Verify the implementation is free of common vulnerabilities and follows secure coding practices.

### How to run

0. **Run STEP 0 triage.** If it returns NARROW, emit the narrow verdict and stop here.
   Everything below is the FULL path. If this is a re-invocation in the same session, use
   the delta re-audit in SKILL.md instead.
1. Read the code — all files touched by the feature or PR.
2. Detect the language and framework automatically.
3. Apply the **universal checklist** below.
4. Apply the **stack-specific checks** for the detected stack (see `references/stacks.md`).
5. Rate each finding against the severity scale in SKILL.md.
6. If any Critical findings exist: **stop and report before proceeding** — do not continue generating code until they are addressed.

### Universal Security Checklist

**Injection**
- [ ] No raw string interpolation into SQL queries — always parameterized
- [ ] No `eval()`, `exec()`, or dynamic code execution with user input
- [ ] Shell commands do not include unsanitized user input
- [ ] Template rendering escapes user content by default (no raw/safe bypasses without justification)

**Authentication & Authorization**
- [ ] Auth checks present on every endpoint/action that requires them
- [ ] Authorization verifies the authenticated user owns or has rights to the specific resource — not just "any authenticated user"
- [ ] No hardcoded credentials, tokens, or secrets in source code
- [ ] Secrets loaded from environment variables or a secrets manager

**Input Validation & Output Encoding**
- [ ] All user-supplied input is validated at the boundary (type, format, length, allowlist where applicable)
- [ ] Output encoding appropriate for context (HTML, JSON, SQL, shell)
- [ ] File uploads: type validated by content (not extension), stored outside webroot, served with correct Content-Type

**Error Handling & Information Disclosure**
- [ ] Error messages do not expose stack traces, internal paths, DB schema, or version info
- [ ] Exceptions are caught and logged internally; users receive a generic message
- [ ] Logs do not contain passwords, tokens, or PII in plaintext

**Cryptography**
- [ ] Passwords hashed with bcrypt/argon2/scrypt — not MD5, SHA1, or reversible encryption
- [ ] Random tokens generated with a CSPRNG, not `rand()`
- [ ] Sensitive cookies have `HttpOnly`, `Secure`, and `SameSite` attributes

**Resource & Business Logic**
- [ ] No mass assignment — only permitted attributes accepted from user input
- [ ] Numeric IDs in URLs validated against the authenticated user's ownership
- [ ] Batch operations have upper bound limits
- [ ] Background jobs do not process untrusted payloads without validation

For stack-specific checks (Rails, Next.js, PostgreSQL, AWS, Node, Python, etc.):
→ See `references/stacks.md`

### Output — IMPL phase

```
## Security Audit: [File / PR / Feature]

### Findings

| # | Severity | Location | Vulnerability | Remediation |
|---|----------|----------|---------------|-------------|
| 1 | 🔴 Critical | `app/controllers/users_controller.rb:42` | IDOR — no ownership check on `params[:id]` | Add `@user = current_user.users.find(params[:id])` |
| 2 | 🟠 High | `lib/importer.rb:18` | Command injection via unsanitized filename | Use `Shellwords.escape` or avoid shell entirely |

### Verdict
🟢 No blockers / 🔴 N critical finding(s) — must fix before continuing
```
