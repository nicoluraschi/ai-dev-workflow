# Edge-case heuristics

Shared checklist. Used by the QA agent (focused: only for the given risk
areas; full: all categories) and by spec reviews to spot undefined
behaviour before implementation.

- **Text input**: empty, whitespace only, very long, accents and ñ,
  emoji, leading/trailing spaces, HTML and script tags, quotes.
- **Numbers**: 0, negative, very large, decimals, comma vs dot as
  decimal separator, non-numeric.
- **Dates and time**: today, past, future, midnight and day boundaries,
  app time zone vs UTC, month and year ends, invalid dates.
- **Collections**: zero items, one, many, pagination limits, sorting,
  filters that return nothing.
- **Auth and ownership**: logged out, another user's resource (change
  the ID in the URL or request), insufficient role.
- **State and flow**: double submit, refresh mid-flow, back button,
  direct URL access to a later step, stale data in two tabs.
- **Errors**: invalid or missing params to the API, what the user sees
  on a validation error, whether their input is preserved.
- **Presentation**: mobile viewport, long text overflow, empty states,
  understandable error and flash messages.
