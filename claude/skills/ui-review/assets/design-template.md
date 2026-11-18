# Design contract — <project>

> Extracted from the codebase and confirmed with the owner. This file is the source
> of truth for `ui-review`. Anything not listed here does not exist: if a screen uses
> a value that is not in this file, that is a finding, not a new convention.

## Personality

Three adjectives, and what this product is explicitly **not**. This is the only
section that cannot be extracted from code — it must be confirmed by the owner.

- Is: <adj>, <adj>, <adj>
- Is not: <adj>, <adj>
- Audience and context of use: <who, on what device, in what situation>
- The one job of the main screen: <one sentence>

## Color

Named values with their meaning. A color without a stated use should be deleted.

| Token | Hex | Used for |
|-------|-----|----------|

Rules:
- Semantic colors (success, warning, danger, info): <list or "none defined yet">
- Neutral ramp: <list>
- Anything outside this table is a finding.

## Typography

- Display / headings: <family, weights>
- Body: <family, weights>
- Type scale actually in use: <list every size found, e.g. 12 / 14 / 16 / 20 / 24 / 32>
- Line heights: <list>
- Maximum line length for body text: <value>

## Spacing

- Scale: <list every value in use, e.g. 4 / 8 / 12 / 16 / 24 / 32 / 48>
- Values found in the code that are outside the scale: <list — these are debt>

## Shape and depth

- Border radii: <list>
- Shadows / elevation levels: <list>
- Borders: <widths and colors>

## Layout

- Breakpoints: <list>
- Container max-width and gutters: <values>
- Grid or column system: <describe or "none">
- Mobile-first: <yes/no>

## Component inventory

What already exists and should be reused before anything new is built.

| Component | Where it lives | States it supports | Notes |
|-----------|----------------|--------------------|-------|

## House rules

Project-specific do's and don'ts discovered or decided along the way.

- Do: <rule>
- Don't: <rule>

## Known inconsistencies

Things that are currently wrong or contradictory in the codebase, listed so they are
not mistaken for conventions. Reviewing a screen against this list is cheaper than
rediscovering them each time.

- <inconsistency> — <where> — <decided resolution, or "undecided">

## References

Products or screens whose approach this project wants to borrow from, and why.

- <reference> — <what specifically is worth borrowing>
