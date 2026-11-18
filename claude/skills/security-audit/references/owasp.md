# OWASP Reference

Loaded on demand when deeper guidance is needed on a specific category.

---

## OWASP Web Application Top 10 (2021)

### A01 — Broken Access Control
The most common and impactful vulnerability class.

**What to look for:**
- Accessing other users' resources by changing a URL parameter or ID
- Elevating privilege by manipulating a role claim or cookie
- Missing authorization on API endpoints (especially non-GET methods)
- CORS misconfiguration allowing unauthorized origins
- Directory traversal through path manipulation

**Required controls:**
- Deny by default — log and alert access control failures
- Enforce ownership checks at the data layer, not only the controller
- Invalidate sessions on the server side on logout
- Limit API access with rate limiting and logging

---

### A02 — Cryptographic Failures
Previously "Sensitive Data Exposure" — focuses on the root cause.

**What to look for:**
- Passwords stored as plaintext or with MD5/SHA1
- Sensitive data transmitted over HTTP
- Weak or outdated cipher suites
- Hardcoded encryption keys
- Random tokens generated with non-cryptographic PRNGs

**Required controls:**
- TLS 1.2+ for all data in transit; HSTS enabled
- bcrypt, argon2id, or scrypt for password hashing (cost factor ≥ 10)
- AES-256-GCM or ChaCha20-Poly1305 for data at rest
- `SecureRandom` or OS-level CSPRNG for tokens

---

### A03 — Injection
SQL, NoSQL, LDAP, OS command, and template injection.

**What to look for:**
- String concatenation into SQL queries
- `eval()`, `exec()`, `system()` with user input
- Template engines rendering unescaped user content
- XML/JSON parsers processing external entity definitions (XXE)

**Required controls:**
- Parameterized queries / prepared statements for all DB access
- Input validation: allowlist known-good values
- Use ORMs correctly — avoid `.where("column = #{value}")` patterns
- Disable XML external entity processing

---

### A04 — Insecure Design
Threat modeling and security requirements missing from the design phase.

**What to look for:**
- No rate limiting on authentication or sensitive flows
- No account lockout after repeated failures
- Business logic allows unreasonable operations (refund more than purchase, free trial reuse)
- Missing audit trail for sensitive mutations

**Required controls:**
- Threat model before implementation (STRIDE — covered in Phase 1)
- Security requirements explicitly listed in the spec
- Abuse case testing alongside happy-path tests

---

### A05 — Security Misconfiguration
Default configurations, unnecessary features enabled, verbose error messages.

**What to look for:**
- Default admin credentials not changed
- Unnecessary HTTP methods enabled (TRACE, DELETE on public resources)
- Verbose stack traces in production error responses
- Unnecessary ports, services, or cloud permissions open
- Missing security headers

**Required security headers:**
```
Content-Security-Policy: default-src 'self'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=()
Strict-Transport-Security: max-age=63072000; includeSubDomains
```

---

### A06 — Vulnerable and Outdated Components
Third-party libraries with known CVEs.

**What to look for:**
- Dependencies pinned to old versions with known CVEs
- No automated dependency scanning in CI
- Abandoned libraries with no security updates

**Required controls:**
- `bundle audit` (Ruby), `npm audit` (Node), `pip-audit` (Python) in CI
- Dependency update automation (Dependabot, Renovate)
- Track EOL dates for runtimes and frameworks

---

### A07 — Identification and Authentication Failures
Weak auth, credential stuffing, session management flaws.

**What to look for:**
- Permits weak or known-compromised passwords
- No protection against credential stuffing (rate limit + lockout)
- Insecure "forgot password" flows (token too long-lived, reusable, or predictable)
- Session IDs in URLs
- Sessions not invalidated after logout

**Required controls:**
- NIST 800-63b password guidance (length over complexity)
- MFA option for sensitive accounts
- Short-lived session tokens; rotate on privilege change
- Secure + HttpOnly + SameSite cookies

---

### A08 — Software and Data Integrity Failures
CI/CD pipeline attacks, deserialization, unsigned updates.

**What to look for:**
- Auto-update mechanisms with no signature verification
- Deserialization of untrusted data (Java ObjectInputStream, Ruby Marshal, Python pickle)
- Third-party scripts loaded without Subresource Integrity (SRI) hashes
- No integrity checks in the deployment pipeline

**Required controls:**
- Pin and verify third-party packages (lockfiles + checksums)
- Avoid native deserialization of user-controlled data; use JSON/Protobuf
- SRI for external scripts and stylesheets in HTML
- Code signing and pipeline integrity checks

---

### A09 — Security Logging and Monitoring Failures
Unable to detect or respond to breaches.

**What to look for:**
- Login failures, access control failures, and input validation failures not logged
- Logs contain sensitive data (passwords, tokens, PII)
- No alerts for anomalous activity
- Logs only stored locally (no central sink)

**Required controls:**
- Log auth events, access denials, and input validation failures
- Centralize logs; retain for ≥ 90 days
- Alert on repeated auth failures, unusual volumes, or admin actions
- Never log credentials or sensitive PII

---

### A10 — Server-Side Request Forgery (SSRF)
The server is tricked into making requests to unintended locations.

**What to look for:**
- User-supplied URLs fetched server-side (webhooks, URL-to-PDF, image import)
- URL validation done only by checking the string, not the resolved IP
- Access to cloud metadata endpoints (169.254.169.254) from web app context
- Internal services accessible from the app server that shouldn't be user-reachable

**Required controls:**
- Allowlist permitted URL schemes and destinations
- Validate the resolved IP after DNS resolution — block RFC1918 and loopback
- Use a dedicated outbound proxy that enforces network-level restrictions
- Disable HTTP redirects or validate redirect destinations

---

## OWASP API Security Top 10 (2023)

Relevant when the project exposes an API (REST, GraphQL, WebSocket).

| # | Name | Key risk |
|---|------|----------|
| API1 | Broken Object Level Authorization | Accessing other users' objects via ID manipulation |
| API2 | Broken Authentication | Weak tokens, no expiry, credential stuffing |
| API3 | Broken Object Property Level Authorization | Over-posting / mass assignment; exposing sensitive fields |
| API4 | Unrestricted Resource Consumption | No rate limits, no pagination limits, no payload size caps |
| API5 | Broken Function Level Authorization | Non-admin calling admin endpoints |
| API6 | Unrestricted Access to Sensitive Business Flows | Bulk purchase, fake account creation, scraping |
| API7 | Server-Side Request Forgery | Same as A10 above |
| API8 | Security Misconfiguration | Same as A05 above |
| API9 | Improper Inventory Management | Shadow APIs, old API versions still accessible |
| API10 | Unsafe Consumption of APIs | Trusting third-party API responses without validation |

For every REST or GraphQL API: ensure API1, API3, API4, and API5 are explicitly addressed in the design.
