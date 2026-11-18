---
name: frontend-iteration
description: Per-project design context loader. Use before any UI work in a project that has an established visual identity. Loads the project's design contract, component inventory, and CSS/Tailwind config so UI changes stay consistent. This is the project's source of truth for frontend — start here before reaching for ui-review or frontend-design.
---

# Frontend iteration

This skill is a **per-project template**. Copy it into a project's `.claude/skills/` directory
and it becomes that project's frontend authority — the first thing loaded before any UI work.

## What this skill does

Before writing or reviewing any UI code, load the project's design context so every decision
is grounded in what already exists, not invented fresh.

## Step 1 — Load the design contract

Read `docs/design.md`. This file is the source of truth for colors, typography, spacing, shape,
layout, and component inventory. If it does not exist:

1. Stop. Use the template at `assets/design-template.md` (bundled with `ui-review`) to create it.
2. Extract values from the actual code: Tailwind/CSS config, global stylesheets, existing components.
3. Ask the human to confirm the personality section (adjectives, audience, what the product is not).
4. Commit `docs/design.md` before proceeding with any UI work.

## Step 2 — Load the CSS/styling config

Read the project's styling configuration to understand the available tokens:

- **Tailwind**: `tailwind.config.*` — theme extensions, custom colors, spacing, fonts.
- **CSS custom properties**: global stylesheet or `:root` variables.
- **Component library config**: if using a UI library (shadcn, Radix, etc.), read its config.

Cross-check: values in the styling config should match `docs/design.md`. Flag any drift.

## Step 3 — Load the component inventory

Scan the project's component directory (typically `app/components/`, `src/components/`,
`app/views/components/`, or similar). Build a mental map of:

- What components exist and what states they support.
- Which are reusable vs. page-specific.
- Naming conventions and file organization patterns.

**Rule: reuse before creating.** Never build a new component when an existing one covers the need.
Say explicitly which existing components are being reused.

## Step 4 — Apply the loaded context

With the design contract, styling config, and component inventory loaded:

- **New UI**: compose from existing components and tokens. Propose layout directions that use
  established patterns. Any genuinely new element gets described in one paragraph first.
- **UI changes**: verify the change stays within the contract. Any new value (color, spacing,
  radius) that isn't in `docs/design.md` is a decision — flag it, don't introduce it silently.
- **UI review**: hand off to `ui-review` with the context already loaded. The review skill
  checks against `docs/design.md` — this skill ensures it exists and is current.

## Customization (per project)

When copying this template into a project, add project-specific details below:

### Project paths
- Design contract: `docs/design.md`
- Styling config: <!-- e.g. tailwind.config.ts, app/assets/stylesheets/application.css -->
- Component directory: <!-- e.g. app/components/, src/components/ -->

### Project-specific rules
<!-- Add any project-specific frontend rules, conventions, or constraints here -->
