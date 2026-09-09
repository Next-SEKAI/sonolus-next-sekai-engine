# Timescale and scroll transitions

Each marker selects its outgoing transition: `TIMESCALE` (the default) or `SCROLL`.
Both support held, linear, quadratic in, out, in-out and out-in easing. Groups may
alternate styles. Groups containing scroll transitions require positive speeds
and no skips; ordinary timescale groups retain stops, reversals and skips.

In Python authoring, set `LevelTimescaleChange.transition_style` and
`timescale_ease` using `TransitionStyle` and `EaseType`. The exported fields are
`transitionStyle` (0 timescale, 1 scroll) and `#TIMESCALE_EASE` (0 through 5 in the
order above). Existing charts default to timescale transitions. Equal-time
markers keep their authored order; queries see the completed final state. The
last marker holds its speed indefinitely.

Hit times do not change. For an interval from `a` to `b`, distance obeys
`D(a,h) = B + R * D(b,h)`:

- Timescale: `R = 1`, `B = integral(speed, a, b)` plus the destination skip.
- Scroll: `R = speed(a) / speed(b)`, `B = speed(a) * (b-a)`.

## Implementation

Native polynomial integration handles the six easings. Timescale positions store
whole scaled seconds separately from the fractional remainder, so short distances
do not subtract two large single-precision clocks.

Consecutive markers of the same style form a run. Timescale distances within a run
use position differences; scroll distances use `speed(now) * (hit-now)`. Each run
start also stores one immutable block summary spanning up to a power-of-two number of
runs. Mixed queries use whole blocks plus their partial endpoint runs. The
summaries store logarithmic gains and positive distances in both directions,
avoiding overflow and subtraction of large nearly equal logarithms on reverse
queries. Preprocessing builds the blocks from right to left.

Consumers cache a distance at the current run boundary. The cache stays fixed
within that run and is recomputed when the run changes, including after a seek.
Its value comes from immutable marker data, so frame count cannot accumulate
drift. Group updates compute the boundary-to-current-time transformation once
for all active consumers. A same-event timescale query integrates the short
interval directly to preserve accuracy near a hit.

Groups update before their active consumers. Consumer registrations include
attachment anchors and hiding state, and preserve the final play cleanup frame.
Notes, connectors and SimLines own their runtime caches.

## Architecture choice

Separate worktree prototypes compared these approaches using matched compiled
fixtures. The fixed boundary cache with the small run index was selected.

| Approach | Main tradeoff |
|---|---|
| Stateless transition traversal | Less stored state, but repeated work becomes excessive on dense charts and signed reentry. |
| Per-frame distance updates | Requires refresh, skipped-frame, seek and saturation rules; often costs more per consumer. |
| Fixed boundary cache with run scan | Simple and stable, but simultaneous cache refreshes repeat long scans. |
| Fixed boundary cache with run index | Adds five marker fields and roughly 48 lines; substantially reduces measured boundary work. |

In a balanced 24-note, six-second stream fixture, indexing reduced boundary work
from 162,782 to 48,803 VM operations. Warm work increased from 2,925 to 3,237.
These are interpreter counts, not device frame timings. Full per-note/marker
tables were rejected because storage grows with the product of notes and markers.

## Spawning

Spawning uses conservative distance bounds over each continuous marker interval.
Monotone eased speeds provide bounds for the interval's interior, including
visibility islands that endpoint sampling could miss. The search subdivides an
overlapping interval until it is small, then returns its early boundary with a
small time margin. It handles instantaneous changes separately.

The search retains at least the existing `[-3, 6]` progress allowance and includes
stage offset bounds. Attachments and connectors use the hull of their sources.
Some notes can spawn before they are visible; this is an intentional tradeoff for
a small implementation. A `0.01` scaled-distance allowance covers practical
rounding at visibility tangencies. Near very flat reversals it can mean several
seconds of extra lead time. Nonnegative, chronologically queried sources can
reuse the previous search position. Signed groups use the general search.
Each search locates its targets once and advances its own source cursors.

## Scope and validation

This is practical floating-point arithmetic, not a formal error certificate. Tests
cover ordinary speed changes, long charts, seeks, signed timescales, and transition
boundaries. Extreme authored speeds and fields outside ordinary numerical range
do not carry an unlimited precision promise.

Select **Timescale and Scroll Demo** to test the transitions: 329 center-lane taps,
evenly spaced 0.25 seconds apart, with sections for each easing and mixed styles.

The earlier certified implementation is preserved in checkpoint `37cdfc6`.
The final optimized build compiled all 140 callbacks in 32.49 seconds, versus
1,810 seconds at that checkpoint. Compressed Play/Watch data is 0.94/0.90 MB.
The four core timescale modules shrank from 3,275 to 1,013 lines.

All 80 feature tests pass. Additional instruction-level checks execute actual
preprocessing on 20,000-marker, 30-minute charts. Maximum normalized position
error was `6.60e-6` across binary32 and mixed binary64/binary32 models. A separate
240-case compiled spawn sweep found no late spawns, including long signed
tangencies; its largest conservative lead was 8.18 seconds on a flat reversal.
The existing unrelated suite has the same failure identifiers as its baseline.

Reproduce the feature suite and optimized build from the repository root:

```sh
uv run python -m unittest discover -s tests -p 'test_timescale_*.py'
uv run sonolus-py build sekai -O2 --gc
```
