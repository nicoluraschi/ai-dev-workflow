# Design principles

Read this in both modes. Every finding and every proposal must cite at least one
principle from here by name. If no principle applies, what is being reported is
personal preference and must be labelled as such.

The point is not to sound authoritative — it is to give the user vocabulary they can
reuse without this skill.

## Contents

1. Grouping and proximity
2. Hierarchy
3. Alignment
4. Contrast
5. Consistency
6. Whitespace and density
7. Decision cost
8. Progressive disclosure
9. Scanning
10. Affordance and feedback
11. Restraint

---

## 1. Grouping and proximity

Elements that belong together must be closer to each other than to elements that do
not. Spacing is the primary carrier of meaning about structure — before borders,
before boxes, before background colors.

**Failure mode:** uniform spacing everywhere. When the gap between a title and its
description equals the gap between two unrelated cards, the user has to read to find
the structure instead of seeing it.

**Fix pattern:** define spacing in relationships, not absolutes — inner gap must be
smaller than outer gap, consistently. If a group still does not read as a group after
fixing proximity, *then* consider a border or a background.

## 2. Hierarchy

Every screen has one primary thing. Hierarchy is the deliberate ordering of what the
eye finds first, second and third. It is built with size, weight, color, position and
space — in that rough order of strength.

**Failure mode:** everything is emphasized, so nothing is. Three buttons of equal
visual weight; five headings at the same size; bold used on half the text.

**Fix pattern:** name the single job of the screen, then rank every element by how
much it serves that job. Anything in the bottom half should get quieter, not louder.
Demoting is usually cheaper and better than promoting.

**Concrete test:** blur the screenshot heavily. Whatever is still legible as a shape
is the hierarchy. If nothing dominates, the hierarchy is flat.

## 3. Alignment

Elements should share edges. Every distinct left edge on a screen is a line the eye
has to track; fewer lines means less work.

**Failure mode:** centered text mixed with left-aligned text; icons and labels that
do not share a baseline; cards whose internal content starts at different offsets.

**Fix pattern:** pick one alignment axis per region and hold it. Center alignment is
for short, isolated content (empty states, single-column hero) — never for lists or
paragraphs.

## 4. Contrast

Contrast is what makes something perceivable and what makes it important. It applies
to color, but also to size, weight and shape.

**Failure mode:** grey text on grey backgrounds for "subtle" secondary information;
disabled states indistinguishable from enabled ones; a primary button that differs
from a secondary one only by a slightly different shade.

**Fix pattern:** if two things must be told apart, they must differ on at least two
axes (color and weight, size and position). Color alone fails for a meaningful share
of users and in bright sunlight — relevant for anything used outdoors or on the move.

## 5. Consistency

The same thing should look the same everywhere, and different things should look
different. Consistency is what lets a user learn an interface once.

**Failure mode:** three card styles for the same kind of object; the same action
labelled "View" in one place and "Open" in another; four radii in use.

**Fix pattern:** consistency beats local optimization. A slightly worse component
used everywhere is better than a slightly better one used in one place. This is the
principle the design contract exists to enforce.

## 6. Whitespace and density

Whitespace is a design element, not leftover. Density is a deliberate choice tied to
the user's context: a tool used for hours wants density; something scanned on a phone
for thirty seconds wants air.

**Failure mode:** cramming, usually caused by trying to avoid scrolling. Scrolling is
free on mobile and always has been; cramped layouts are not.

**Fix pattern:** state the intended density for the product in the design contract,
then apply it uniformly. Do not mix a dense table with an airy card grid in one view
without a reason.

## 7. Decision cost

Every visible option costs the user attention, whether or not they use it. More
choices means slower decisions, not richer ones.

**Failure mode:** eight filters exposed at once because each one is individually
justifiable. A toolbar with every action at equal weight.

**Fix pattern:** rank the options by real usage — analytics beats intuition here.
Keep the top two or three visible, put the rest behind one control. Then measure again.

## 8. Progressive disclosure

Show what is needed for the current decision; keep the rest one step away. This is
how a small screen carries a lot of information without becoming a wall.

**Failure mode:** the opposite error is also common — hiding something the user needs
on every visit, so every visit costs an extra tap.

**Fix pattern:** the test is frequency, not importance. Frequently needed goes on the
surface even if it is minor; rarely needed goes away even if it is significant.

## 9. Scanning

People scan before they read, in predictable shapes: down the left edge, along the
first line, in an F or Z pattern depending on layout. Lists are scanned by their
first few characters.

**Failure mode:** the distinguishing information of a list item is buried at the end
of a line or in the second row, so every item looks the same while scanning.

**Fix pattern:** put the discriminating attribute first. In a list of similar items,
whatever the user compares on belongs at the start of the line or in a fixed,
predictable position across every item.

## 10. Affordance and feedback

Interactive things must look interactive, and every action must produce a visible
response within about 100ms — even if the result takes longer.

**Failure mode:** clickable cards with no hover or pressed state; a submit that looks
identical for the two seconds before the response arrives; errors that appear far
from the field that caused them.

**Fix pattern:** every interactive element needs default, hover, focus, active and
disabled. Every async action needs an immediate acknowledgement. Errors appear next
to their cause, in the interface's voice, saying what to do.

## 11. Restraint

The strongest design decision is usually a removal. A design with one memorable idea
and quiet surroundings beats one with four competing ideas.

**Failure mode:** additive drift — each individually reasonable addition accumulates
into noise. This is what happens to a product over months without anyone deciding it.

**Fix pattern:** in every review, propose at least one thing to remove. If nothing can
be removed, say so explicitly — that is a real and reportable outcome.
