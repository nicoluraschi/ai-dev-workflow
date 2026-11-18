# Stack-Specific Security Checks

Loaded during Phase 3 (IMPL) once the stack is detected. Apply the relevant section(s) on top of the universal checklist in `references/impl.md`.

---

## Ruby on Rails

### Detection
Files: `Gemfile`, `*.rb`, `config/routes.rb`, `app/controllers/`

### Critical checks

**Mass Assignment**
```ruby
# ❌ Never
User.create(params[:user])

# ✅ Always use strong parameters
def user_params
  params.require(:user).permit(:name, :email)
end
```

**SQL Injection**
```ruby
# ❌ Vulnerable
User.where("email = '#{params[:email]}'")
User.where("name LIKE '%#{query}%'")

# ✅ Safe
User.where(email: params[:email])
User.where("name LIKE ?", "%#{query}%")
```

**Authorization — IDOR**
```ruby
# ❌ Fetches any record — IDOR if ID is user-controlled
@post = Post.find(params[:id])

# ✅ Scoped to the authenticated user
@post = current_user.posts.find(params[:id])
```

**CSRF**
- `protect_from_forgery` enabled for HTML forms (default in Rails)
- API-only apps using token auth: verify `protect_from_forgery with: :null_session` or `with: :exception` is intentional
- Check that CSRF tokens are not leaked in JSON responses

**File Uploads (ActiveStorage / CarrierWave)**
```ruby
# Validate content type by magic bytes, not extension
validates :attachment, content_type: ['image/png', 'image/jpeg']
# Store outside public/ or use a CDN — never serve from /public with user-controlled filename
```

**Secrets**
- Check `config/credentials.yml.enc` — credentials should be encrypted, not plaintext
- No secrets in `config/database.yml` committed to source — use `ENV[...]`
- `config/secrets.yml` should not exist in modern Rails apps

**Routing**
- `resources :users` generates PATCH/DELETE — verify auth on all actions
- Check `skip_before_action :authenticate_user!` usages — each one is a potential auth bypass

**Gems to flag for review**
- `devise` — check `config/initializers/devise.rb` for secure password settings (min length, lockout)
- `pundit` / `cancancan` — verify policy/ability files cover every controller action
- `rack-cors` — verify `origins` is not `'*'` in production

---

## Next.js / React

### Detection
Files: `package.json` with `next`, `*.tsx`, `*.jsx`, `pages/`, `app/`

### Critical checks

**Server Actions / API Routes — Auth**
```typescript
// ❌ No auth check
export async function DELETE(req: Request) {
  await db.post.delete({ where: { id: params.id } })
}

// ✅ Auth checked before every mutation
export async function DELETE(req: Request) {
  const session = await getServerSession(authOptions)
  if (!session) return new Response(null, { status: 401 })
  // then verify ownership before deleting
}
```

**IDOR in Server Components**
- Data fetched with `params.id` must be scoped to the authenticated user's data
- Never assume a URL param is safe to use directly as a DB key

**Environment Variables**
- `NEXT_PUBLIC_` prefix exposes the value to the browser bundle — verify only non-sensitive values use it
- Secrets (DB URLs, API keys, signing keys) must use non-public env vars accessed only in server code

**Content Security Policy**
- Check `next.config.js` for `headers()` — CSP, HSTS, X-Frame-Options should be present
- `dangerouslySetInnerHTML` usage: every instance needs justification — verify input is sanitized or from a trusted source

**Dependency risks**
- `npm audit` — flag any high/critical CVEs
- Check for `eval()` patterns in bundled code

---

## PostgreSQL

### Detection
Database config files, `schema.rb`, `*.sql`, migration files.

### Critical checks

**Query construction**
- Raw `EXECUTE` or `PERFORM` in plpgsql functions: parameterized?
- `pg_query` or any raw query builder: bound parameters used?

**Permissions**
- Application DB user should NOT be the owner of the schema
- Application user should have only `SELECT`, `INSERT`, `UPDATE`, `DELETE` on app tables
- No `SUPERUSER` for the application role
- Migrations may need a separate privileged role — check it's not used at runtime

**Sensitive data at rest**
- PII columns: are they encrypted (`pgcrypto`, application-level encryption)?
- Audit log: triggers or application-level logging for mutations to sensitive tables?

**Connection**
- SSL mode: `sslmode=require` or `verify-full` in production connection string
- Connection pooler (PgBouncer) configured in transaction mode for stateless auth

---

## AWS

### Detection
Files: `*.tf`, `*.yaml` with AWS resources, `config/aws.yml`, SDK usage.

### Critical checks

**IAM**
- No `"*"` in `Action` or `Resource` for application roles
- EC2/Lambda/ECS roles: principle of least privilege — only the actions the service actually needs
- No IAM access keys hardcoded in source or environment variables committed to source
- Access keys should be rotated; prefer instance roles / IRSA over long-lived keys

**S3**
- Buckets are private by default — `Block Public Access` enabled at account and bucket level
- User-uploaded content served through CloudFront or pre-signed URLs, not public bucket URLs
- Bucket policies do not use `"Principal": "*"`
- Server-side encryption enabled (SSE-S3 or SSE-KMS)

**Secrets Manager / Parameter Store**
- Database credentials, API keys, and signing secrets retrieved from Secrets Manager at runtime
- No plaintext secrets in Lambda environment variables (use encrypted parameters)

**Networking**
- RDS not publicly accessible (`publicly_accessible = false`)
- Security groups: inbound rules scoped to minimum required — no `0.0.0.0/0` on DB ports
- VPC: application servers and databases in private subnets; only load balancers in public subnets

**Logging**
- CloudTrail enabled across all regions
- S3 access logging enabled on sensitive buckets
- VPC Flow Logs enabled in production

---

## Node.js (general / Express / Fastify)

### Detection
`package.json` without `next`, `*.js`/`*.ts` server files, Express/Fastify imports.

### Critical checks

**Injection**
```javascript
// ❌ Command injection
exec(`convert ${req.body.filename} output.pdf`)

// ✅ Avoid shell; use library directly or sanitize
execFile('convert', [sanitizedFilename, 'output.pdf'])
```

**Prototype Pollution**
- `_.merge`, `Object.assign`, or deep-merge with user input: check for prototype pollution protection
- Use `Object.create(null)` for objects that hold user-controlled keys

**Authentication middleware order**
- Auth middleware must be applied before any route handler that requires auth
- Verify wildcard routes don't bypass auth middleware

**npm packages**
- `npm audit` in CI — flag critical/high CVEs
- Minimize use of packages with OS-level access (`child_process`, `fs`) from user-facing code

---

## Python (Django / FastAPI / Flask)

### Detection
`requirements.txt`, `pyproject.toml`, `*.py`, framework-specific files.

### Critical checks

**Django**
```python
# ❌ Raw query with string formatting
User.objects.raw(f"SELECT * FROM auth_user WHERE name = '{name}'")

# ✅ Parameterized
User.objects.raw("SELECT * FROM auth_user WHERE name = %s", [name])
```
- `ALLOWED_HOSTS` set and not `['*']` in production
- `DEBUG = False` in production
- `SECRET_KEY` from environment, not hardcoded
- `CSRF_COOKIE_SECURE` and `SESSION_COOKIE_SECURE` = `True` in production

**FastAPI**
- Pydantic models validate all input by default — verify no `model_config = ConfigDict(extra='allow')` on security-sensitive models
- OAuth2 scopes defined and checked on protected routes
- Background tasks: validate all inputs before enqueuing

**General Python**
- `pickle.loads()` with untrusted data: critical injection risk — use JSON instead
- `subprocess` with `shell=True` and user input: command injection risk
- `eval()` / `exec()` with user input: never acceptable

---

## General: Secrets & Environment

Applies to all stacks.

### Never in source code
- Database URLs with credentials
- API keys (Stripe, SendGrid, Twilio, AWS, etc.)
- JWT signing secrets
- OAuth client secrets
- Private keys (RSA, ECDSA)
- Encryption keys

### Always in environment / secrets manager
- Load from `ENV`, `process.env`, `os.environ` at runtime
- Use `.env.example` with placeholder values committed; `.env` in `.gitignore`
- In CI/CD: inject via secrets manager (GitHub Actions secrets, AWS Secrets Manager, HashiCorp Vault)
- Rotate after any accidental exposure; invalidate old credentials immediately

### Pre-commit defense
- `gitleaks` or `truffleHog` pre-commit hook to prevent accidental commits
- GitHub secret scanning enabled on the repository
