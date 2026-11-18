## PHASE 1: SPEC — Threat Modeling

**Goal:** Identify what can go wrong before anything is built.

### Steps

1. **Extract assets** — What data or capabilities does this feature protect? (user data, money, admin access, secrets, third-party credentials)
2. **Map trust boundaries** — Who are the actors? (anonymous user, authenticated user, admin, external service, background job) What can each actor touch?
3. **Apply STRIDE** — For each asset/boundary pair, enumerate threats:
   - **S**poofing: Can an actor impersonate another?
   - **T**ampering: Can data be modified in transit or at rest without authorization?
   - **R**epudiation: Can an actor deny an action they took?
   - **I**nformation disclosure: Can data be exposed to unauthorized actors?
   - **D**enial of service: Can the feature be made unavailable?
   - **E**levation of privilege: Can an actor gain capabilities they shouldn't have?
4. **Rate each threat** using the output format below.
5. **Produce security requirements** — Concrete, testable conditions the design must satisfy.

### Output — SPEC phase

```
## Security Threat Model: [Feature Name]

### Assets & Trust Boundaries
- Assets: [list]
- Actors: [list with privilege level]
- Key boundaries: [where trust changes]

### Threats Identified

| # | STRIDE | Threat | Likelihood | Impact | Risk |
|---|--------|--------|------------|--------|------|
| 1 | I | Unauthenticated endpoint exposes user emails | High | High | 🔴 Critical |
| 2 | E | Role check missing on admin action | Med | High | 🟠 High |
| 3 | D | No rate limit on search endpoint | Med | Med | 🟡 Medium |

### Security Requirements (must satisfy before design closes)
- [ ] [Requirement 1]
- [ ] [Requirement 2]

### Deferred (acceptable risk or out of scope)
- [Threat N]: [reason it's deferred]
```
