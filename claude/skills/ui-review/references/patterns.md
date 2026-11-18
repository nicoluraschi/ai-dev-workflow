# Patterns

Canonical solutions for recurring interface problems, with the mistakes each one
usually attracts. Use these as precedent when proposing changes: naming the pattern
and where it is established is more useful to the user than describing a shape.

These are starting points, not mandates. If the project's design contract contradicts
one of these, the contract wins.

## Contents

1. Filterable list
2. List item / card
3. Filter controls
4. Empty and zero-result states
5. Loading
6. Errors and validation
7. Detail view
8. Forms
9. Navigation on small screens
10. Dates and quantities

---

## 1. Filterable list

The dominant pattern: filters fixed and always reachable, results reacting
immediately, result count visible at all times, active filters shown as removable
chips, and a one-tap way to clear everything.

- Filtering happens on change, not behind an "Apply" button, unless each query is
  expensive.
- The result count is not decoration — it is what tells the user whether their filter
  did something. `24 results` after filtering is the difference between confidence
  and doubt.
- Active filters must be visible without opening the filter panel. Chips do this best.
- Sort and filter are different things and should not share a control.
- On mobile, filters usually live in a sheet or drawer opened from a sticky bar; the
  bar shows how many filters are active.

**Common mistakes:** filters that silently produce zero results with no explanation;
no way to tell what is currently filtered after scrolling; a "clear" that also resets
the sort.

## 2. List item / card

A card in a list of comparable objects exists to support one action: comparing. Every
card must present the same attributes in the same positions, so the eye can compare
down a column rather than re-reading each item.

- Lead with the discriminating attribute — the thing the user is choosing on.
- Two or three attributes maximum on the surface. A card that shows everything is a
  detail view in disguise.
- The whole card is the target, not a small link inside it.
- Visual weight should not vary between items unless the difference is meaningful
  (featured, cancelled, sold out) — and then it must be legible as a category.
- Images earn their place only if they carry information. A generic photo on every
  card adds height without adding a decision input.

**Common mistakes:** attributes in different orders across items; the date rendered
in a format that cannot be scanned; the primary action competing with a secondary
link inside the same card.

## 3. Filter controls

Match the control to the shape of the data:

- Two to five mutually exclusive options → segmented control, all visible.
- Six or more → dropdown or multi-select sheet.
- A continuous range → range control, but only if the user actually thinks in ranges;
  often preset buckets are better ("under $50", "$50–100", "$100+" beats a slider).
- Dates → presets first ("this weekend", "next 30 days"), custom range behind them.

**Common mistakes:** a slider for values that are really a handful of discrete
options; filters presented in an order unrelated to how often they are used;
combinations reachable through the UI that can never return results.

## 4. Empty and zero-result states

There are three different empty states and they need different treatments:

- **First use** — nothing exists yet. Explain what will appear here and give the
  action that creates it.
- **Zero results from a filter** — the content exists but the query excluded it.
  Say which filter is responsible, and offer the single most effective relaxation
  ("nothing in August — see September" beats "no results").
- **Genuinely nothing** — the category is empty for real. Say so plainly and offer
  the nearest useful alternative.

**Common mistakes:** one generic "no results" for all three; a centered illustration
with no next action; leaving the user to guess which of five active filters caused it.

## 5. Loading

- Content that will arrive in a known shape → skeleton matching that shape.
- Unknown duration or shape → spinner, but only after ~300ms, otherwise it flashes.
- Actions triggered by the user → immediate state change on the control itself
  (disabled + label change), not a full-page overlay.
- Never let layout shift when content lands. Reserve the space.

## 6. Errors and validation

- Validate on blur, not on every keystroke; re-validate on change once a field has
  already errored.
- The message goes next to the field, describes what is wrong and what to do, and
  survives until fixed.
- Form-level errors go at the top *and* the first offending field receives focus.
- System errors say what happened and what the user can do now. "Something went
  wrong" with no recovery path is not an error state, it is an apology.

## 7. Detail view

A detail view exists because a list cannot carry everything. Its job is to answer the
questions that decide the action.

- Lead with what the list could not show and what the decision depends on.
- One primary action, visible without scrolling on mobile, and repeated at the end if
  the page is long.
- Related items at the bottom, never competing with the primary action.
- The URL is part of the design: it should be shareable and readable.

## 8. Forms

- One column. Multi-column forms increase errors and break on mobile.
- Labels above fields, always visible. Placeholders are examples, not labels.
- Group related fields with spacing, not with boxes.
- Ask only for what is needed now. Every field costs completion rate.
- The submit button says what it does ("Publish event"), not "Submit".

## 9. Navigation on small screens

- Primary actions within thumb reach — the bottom half of the screen, not the top
  corners.
- Sticky headers cost vertical space; justify them by what they hold.
- Back must be predictable: filters and scroll position survive a return from a
  detail view. Losing filter state on back is one of the most common and most
  frustrating mobile bugs.

## 10. Dates and quantities

- Absolute dates for future events, relative for recent past ("2 days ago").
- Consistent format everywhere, in the user's locale and language.
- Weekday matters when the user plans around it — for weekend events, showing the day
  name is worth the space.
- Units always attached to numbers, formatted the same way in every context.
- Ranges use a consistent separator and ordering.
