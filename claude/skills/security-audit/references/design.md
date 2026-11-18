## PHASE 2: DESIGN — Security Architecture Review

**Goal:** Validate that the design addresses the threats from Phase 1 and introduces no new structural vulnerabilities.

### Checklist (run for every design)

**Authentication & Authorization**
- [ ] Authentication mechanism is explicit — not assumed
- [ ] Authorization is checked at every layer (controller, service, query) — not only at the entry point
- [ ] Privilege checks are deny-by-default; access is granted explicitly
- [ ] Token/session lifetime is defined and appropriate
- [ ] Sensitive actions require re-authentication or additional confirmation

**Data Flow**
- [ ] PII and sensitive data are identified in the data model
- [ ] Sensitive data is encrypted at rest and in transit
- [ ] Data access is scoped to the minimum required (principle of least privilege)
- [ ] Audit trail exists for sensitive data mutations

**API & Interface Design**
- [ ] Every endpoint has a defined auth requirement
- [ ] Input validation is described at the boundary — not left to the implementation
- [ ] Rate limiting strategy is defined for public or auth-critical endpoints
- [ ] Responses do not leak internal identifiers or stack traces
- [ ] IDs exposed in URLs/responses are not directly exploitable (consider UUIDs, slugs, or HMAC-signed tokens)

**External Integrations**
- [ ] Credentials and secrets are never in config files or source code; strategy for injection is defined
- [ ] Outbound requests to external services are validated (no SSRF surface)
- [ ] Webhooks validate the signature of incoming payloads

**Infrastructure**
- [ ] Least-privilege roles for DB access, cloud IAM, service accounts
- [ ] No sensitive values in logs
- [ ] Security headers defined if the design includes a web interface

Read the OWASP reference for in-depth guidance on any category:
→ See `references/owasp.md`

### Output — DESIGN phase

```
## Security Design Review: [Component or Feature]

### Checklist Results (failures only)
❌ [Failed item] — [what's missing and what's needed]
⚠️  [Concern] — [not a blocker but worth noting]

### Gaps (must fix before implementation)
1. [Gap description] — [recommended fix]

### Recommendations (non-blocking)
- [Suggestion]

### Verdict
🟢 Clear to implement / 🔴 Blocked — fix gaps first
```
