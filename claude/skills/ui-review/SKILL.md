---
name: ui-review
description: "Review or build UI in a project that already has a visual identity. Run it AFTER frontend-iteration has loaded the project's design contract — frontend-iteration supplies the context, this skill does the actual review, including the Web Interface Guidelines compliance check. Mandatory before calling any user-facing change done, even when only functionality was requested: fires on 'how does this look', 'review this screen', 'is this well designed', 'what should I improve visually', on any diff touching .tsx/.jsx/.css/Tailwind classes, a page, a component or a layout, and at the Review phase of feature-workflow. For greenfield visual identity with no established look, use frontend-design instead."
---

# UI Review

Findings are **observations tied to rules, with the reasoning visible**, never aesthetic verdicts. Every finding must say *why* it is a problem, not just that it is.

Two modes. Pick one and say which you are in.

- **Review mode** (default) — an existing screen is evaluated and a prioritized list of findings is produced. No code is written until the user picks what to fix.
- **Build mode** — new UI is implemented inside the constraints already established by the project.

---

## Step 0 — Load the project's design contract

Before anything else, read the project's design contract: `docs/design.md` (or wherever the project keeps it).

**If it does not exist, stop and create it first.** Nothing in this skill works without it — without a written contract, every review becomes personal taste and every new screen invents its own conventions. Use `assets/design-template.md` and fill it by:

1. Reading the actual code: Tailwind config, CSS custom properties, global stylesheet, existing components.
2. Screenshotting 3–4 representative screens — in the main session through the `ui-reviewer` agent, as in review mode step 1, which returns a **Draft contract** for you to write; inside a subagent, take them yourself.
3. Extracting what is *actually* being used — the real colors, the real font sizes, the real spacing values.
4. Listing the inconsistencies found rather than silently normalizing them. If there are 11 different spacing values in use, that is a finding, not something to average out.

Show the draft to the user and ask them to confirm the personality section, which is the only part that cannot be extracted from code.

---

## Review mode

### 1. Look at it

Never review UI from source alone. Open the actual page in the browser and capture it at **360px, 768px and 1280px**. Screenshot every state you can reach: default, loading, empty, error, no-results, form validation. If a state cannot be reached, say so — a state you could not find is very often a state that does not exist, and that is itself the finding.

**Who looks.** In the main session, steps 1–4 run inside the `ui-reviewer` agent: it takes the screenshots, does the checks and returns text plus the screenshot paths. The main session never reads an image — each one is re-read on every later turn, and `hooks/main-context-images.py` denies it. Relay the agent's Findings, Proposals, Not checked, Web Interface Guidelines and Principles applied sections to the user **verbatim** — no paraphrase, no dropped rows — then give the screenshot paths for the user to open. Inside a subagent, do the steps yourself.

### 2. Objective checks

These are verifiable, not matters of taste. Check each one and report the actual measured value, not a judgment.

**Accessibility and mechanics**
- Text contrast ≥ 4.5:1 (≥ 3:1 for text above 24px and for UI component boundaries). Report the computed ratio.
- Interactive targets ≥ 44×44px, with ≥ 8px between adjacent targets.
- Keyboard: every interactive element reachable by Tab, focus ring visible against its background, tab order matches visual order.
- Inputs have real labels, not just placeholders. Font size ≥ 16px on mobile inputs (smaller triggers zoom on iOS).
- Images have alt text; decorative ones have empty alt.
- `prefers-reduced-motion` respected wherever there is animation.

**Layout**
- No horizontal overflow at 360px.
- No layout shift when images or async content load.
- Content stays readable between 45–75 characters per line for body text.

**Consistency against the contract**
- Every color, font size, spacing value, radius and shadow used on this screen exists in `docs/design.md`. List every value that does not, with its location. This check catches more real problems than any aesthetic critique.

**Completeness**
- Loading, empty, error and zero-results states exist and are designed, not just absent or default.
- Destructive and irreversible actions are visually distinct from ordinary ones.

### 2b. Web Interface Guidelines check

After the objective checks, fetch the latest Vercel Web Interface Guidelines and cross-check:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

Use WebFetch to retrieve the rules. Apply them to the files touched in this screen and report
any findings in the same `file:line` format. This complements the objective checks above with
industry-standard web UI rules. Skip this step only if the network fetch fails — in that case,
note it was skipped and proceed.

### 3. Subjective pass

Only after the objective checks. Read `references/principles.md` first and frame each
observation as a question answered with evidence from the screenshot, citing the
principle by name.

- What does the eye land on first? Does that match the screen's single job?
  (*Hierarchy* — apply the blur test.)
- Is there exactly one primary action? If two elements compete for primary, name them.
- Does the spacing encode grouping? (*Proximity* — compare inner vs outer gaps.)
- Is color carrying meaning, or decorating? (*Contrast*, *Restraint*.)
- Is the type scale doing hierarchy work, or is everything one or two sizes apart?
- How many distinct left edges are there in this region? (*Alignment*.)
- Scanning a list: is the discriminating attribute first and in the same position on
  every item? (*Scanning*.)
- What could be removed without losing information? (*Restraint* — always answer this
  one, even if the answer is "nothing".)

### 4. Propose, don't only diagnose

This is where the review earns its keep.
Diagnosing without proposing leaves them exactly where they started.

For the top three findings (blockers and majors only, when step 5's report is limited to them), read `references/patterns.md` and produce, for each:

- **Two options**, not one. They must be genuinely different approaches, not the same
  idea at two intensities.
- For each option: the pattern it follows and where that pattern is established, what
  it costs to build, and what it gives up. Every option gives something up — an option
  presented as free is an option that was not thought through.
- **A recommendation** with the reason, tied to the product's stated personality and
  audience from the design contract, not to general taste.

Then let the user choose. Do not implement the recommendation because it was
recommended.

If a proposal cannot be justified by a named principle, an established pattern, or
something in the design contract, say so explicitly: *"this one is my preference, not
a rule."* That label is what keeps the rest of the report trustworthy.

### 5. Report


Output a table, ordered by impact, then one sentence naming the single change with the best ratio of impact to effort. Each row ≤40 words excluding measured values; a screen with no findings is one line (`UI review — <screen>: 🟢 no significant findings`).

| # | Severity | Finding | Evidence | Why it matters | Fix | Effort |
|---|----------|---------|----------|----------------|-----|--------|

- **Severity** is one of:
  - `blocker`: a changed flow cannot be completed or read (an unreachable state, a keyboard trap, content hidden by overflow at 360px, body text contrast below 4.5:1).
  - `major`: any other failed objective check from step 2 (target size, labels, a value not in the contract, a missing loading/empty/error state).
  - `minor`: the subjective pass and labelled preferences.
- **Blockers and majors only**, when the caller asks for it (the light lane does): leave out the `minor` rows, end the table with `Minors omitted: <n>`, and draw step 4's top three from the rows reported. With only minors, the report is the 🟢 line plus that count.
- **Evidence** is a measured value or a screenshot reference, never "it feels cluttered."
- **Why it matters** names the rule or the user consequence. If neither can be named, the finding is taste — drop it or label it explicitly as a preference.
- Cap the report at **8 findings**. A list of thirty gets ignored. If there are more, say how many were left out and why these eight came first.

### 6. Hard rules for review mode

- **Do not redesign.** The screen has an established identity. Proposing a new palette, new typefaces or a new layout concept is out of scope unless the user explicitly asks for a redesign.
- **Do not introduce values that are not in the contract.** Fixes use existing tokens. If a fix genuinely requires a new token, propose adding it to `docs/design.md` as a separate decision.
- **Do not write production code in review mode.** Produce the findings and the options, let the user choose, then implement only what was chosen.
- **Do not pad the list.** Reporting "no significant findings" on a screen that is fine is a valid and useful outcome.
- **Never assert taste as fact.** Anything not backed by a principle, a pattern or the contract gets labelled as preference.

---

## Build mode

1. Read `docs/design.md`, then `references/patterns.md` for the component types involved. Compose from the existing component inventory before creating anything new. Say explicitly which existing components are being reused.
2. **Before writing any code, propose two layout directions** in prose plus rough ASCII wireframes: what each one leads with, which pattern it follows, what it optimizes for and what it sacrifices. Recommend one, with the reason tied to the product's personality and the screen's single job. Wait for the user to pick.
3. If something genuinely new is needed, describe it in one paragraph first: what it is, which existing patterns it borrows from, which tokens it uses.
4. Build mobile-first. The 360px layout is the design; wider viewports are the adaptation.
5. Include all states from the start — loading, empty, zero-results, error — not just the happy path. `references/patterns.md` covers what each one needs.
6. When finished, run the review-mode checklist on your own output before showing it. Report what you checked.

If the project has **no** established identity yet and the task is to create one, this is the wrong skill. Use `frontend-design` for the identity work, then write `docs/design.md` from the result and come back here.

---

## Bundled references

- `references/principles.md` — named design principles, each with its failure mode and fix pattern. Read in both modes; every finding cites at least one by name.
- `references/patterns.md` — canonical solutions per component type (filterable lists, cards, filters, empty states, forms, detail views) and the mistakes each attracts. Read when proposing or building.
- `assets/design-template.md` — the template for a project's `docs/design.md`.

## Anti-patterns

Things that read as machine-generated design and should not appear unless the contract asks for them: decorative gradients, glassmorphism, unmotivated drop shadows on flat layouts, emoji as icons, numbered markers on content that is not a sequence, a new accent color per section, animation without a reason. Also: "modernizing" a screen that was not reported as dated.

## Communication

Name the principle behind each finding in plain language, the way `references/principles.md` phrases them ("related things should be closer together than unrelated things — these two blocks have the same 16px gap but belong to different groups"). Prefer one well-explained finding over five asserted ones. The measure of success is that next time they spot it themselves.
