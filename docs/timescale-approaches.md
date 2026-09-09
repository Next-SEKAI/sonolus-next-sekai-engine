# Timescale implementation alternatives and normalization

Exploratory review supporting the [implementation plan](timescale-transition-design.md).
The intended feature is a per-transition choice of TIMESCALE or SCROLL with the
six existing easing shapes. Hybrid groups are positive and skip-free; signed
legacy timescale stays separate. Runtime updates are the critical performance
constraint. Substantial upfront preprocessing is acceptable.

## Recommendation

Prototype **accurate preprocessing, normalized local coordinates, and caches at
same-style run boundaries** first. Use an immutable transfer tree for arbitrary
alternation, with inexpensive certified summaries in runtime queries. Build the
accurate arithmetic into preprocessing, not automatically into every frame.

Measure the run-switch and seek frames as well as ordinary frames. If unrestricted
alternation still costs too much, a small maximum number of style switches per
group is the preferred feature cut. It preserves arbitrary speed/easing markers
and several handoffs, unlike restricting an entire group to one style.

Normalized blocks are an optional second optimization if actual charts alternate
styles frequently enough to make run-based cache invalidation costly. They add
local-prefix/error/storage complexity and should earn that complexity in measurements.

## What normalization can and cannot do

At an anchor, the coordinate change

~~~
A_new = c * (A - A_anchor)
T_new = c * T
S_new = S / c
~~~

preserves displayed distances. Every cached hit coordinate must be interpreted in
the corresponding new coordinates as well. Power-of-two changes of scale only
adjust binary exponents when the result remains representable; the subtraction
still needs accurate input coordinates. Recentring after information was already
lost does not recover it.

Use immutable local coordinates per event/run/block rather than repeatedly
rebasing every note in the chart. A note stores its anchor reference and a local
target value. Cross-anchor transfers supply the unit conversion, so inactive
notes and attachment endpoints do not need an O(N) rewrite on each normalization.

For example, choose T_local(a)=1, S_local(a)=v(a), A_local(a)=0:

| Event style | Local T | Local S |
|---|---|---|
| Timescale | v(t)/v(a) | v(a) |
| Scroll | 1 | v(t) |

For positive ordinary speed ratios these local values are well conditioned. The
next event may choose a fresh coordinate system. Its bridge is still required.
Setting that bridge to identity changes the chart.

Separate three issues:

| Issue | Treatment |
|---|---|
| Old global prefixes destroy small nearby differences | Local coordinates and direct local integration |
| A true long-range conversion exceeds scalar range | Explicit exponent, or a proved restriction on history |
| Many rounded ratios accumulate error | Accurate aggregate construction, cancellation of exact same-style factors, and runtime error budgets |

Resetting units every 32 events solves neither the last issue nor all possible
long-range conversions. The exploratory binary32 experiment obtained the same
ratio drift with 32-event blocks as with the full event tree.

## A. Accurate preprocessing, scalar runtime summaries

The central transfer is D(a,h)=R*D(b,h)+B. Build each subtree's R/B accurately from
authored endpoints using normalized high/low arithmetic plus an exponent. Publish
rounded scalar mantissas with exponents and conservative error bounds for queries.

**A parent must consume accurate children, not their rounded published summaries.**
Otherwise all the old leaf-division errors remain. Two storage/work choices are:

1. Retain accurate high/low fields in marker data through the tree build. At runtime,
   read the rounded high component and enlarge its bound by the omitted low part.
2. Independently replay each subtree accurately during preprocessing, then retain
   only its rounded summary. This takes O(E log E) work, around 300,000 leaf visits
   for 20,000 markers. It trades more upfront work for fewer persistent fields.

For distance-only queries, process canonical covering nodes right-to-left:

~~~
x = R_node*x + B_node
~~~

There is no need to construct the query's combined R. With about 30 nodes, a basic
rounding estimate is approximately 3*k*u, or 5.4e-6 relative for binary32 before
the remaining certificates. The estimate depends on query length, not all E
authored factors, because each stored coefficient was accurately preprocessed.
Use the actual geometry/preempt multiplier before deciding whether this fits
the 1e-4 absolute progress budget.

Normal frames apply one group-shared local transfer to one cached boundary value.
If a rounded-summary query's certificate is insufficient, an accurate refresh can
occur at an anchor change or seek; it should not become routine per-frame work.
Alternatively, narrow the supported switch/geometry envelope. Previously rounded
values do not become accurate merely by multiplying them with high/low arithmetic.

This is the best first prototype because it preserves one representation and
moves the expensive arithmetic into the user's preferred upfront phase.

## B. Same-style runs: fewer refreshes without changing semantics

Consecutive same-style transitions can share an anchor even when their speeds and
easing change repeatedly. Their complete transfers telescope exactly:

~~~
Timescale run: R=1;             B=integral[run_start,run_end] v
Scroll run:   R=v_start/v_end;  B=v_start*(run_end-run_start)
~~~

Retain all internal markers for current speed, hiding, partial queries and spawn
search. Coalescing the full transfer does not replace the internal trajectory.
At same-time batches, preserve ordered suboperations when deriving runs; a batch
that changes style can contain several run transitions despite having zero duration.

Cache D(run_end,h) for future targets beyond the current run. Timescale runs use
precomputed local integral suffixes; scroll runs use their exact endpoint ratio
and duration. Internal easing events update the group's local state without
invalidating every note cache. Same-run scroll targets use v(t)*(h-t); same-run
timescale targets use accurate local integral differences, with direct same-event
integration near the hit.

Build prefix/suffix sums accurately in preprocessing and preserve high/low components.
Do not subtract rounded scalar prefixes. A conservative proof must include sum and
subtraction error; sharing the same historical terms allows their modeling error
to cancel, but it does not excuse numerical cancellation in stored values.

The main benefit is fewer event-change spikes: note caches refresh on actual style
switches, not every speed marker. A seek within the same immutable run preserves
the boundary value, while time-dependent group state still refreshes.

## C. Normalized blocks with a tree over block roots

Blocks can retain caches across several style switches. An initial experiment can
use at most 32 events per block, additionally split by gauge, duration and arithmetic
conditioning. An individual event with ratio 160 keeps its direct exact kernel.

For block start a, use

~~~
s(t)=S(t)/S(a)
X(t)=S(a)*integral[a,t] T
D(t,h)=s(t)*(X(h)-X(t))       when both times are in the block
~~~

Precompute event-local gauges, high/low prefixes and backward suffixes within the
block. Tree roots store the block-to-block scaled transfer. Far targets cache a
distance at block end, so event changes inside the block cost one group update.
Past targets use the block start and a positive-magnitude oriented update; never
advance cached future distances by cancellation-prone forward subtraction.

Near targets inside a block need certified local prefix differences or direct
event-fragment evaluation. Choose block bounds from the final progress error,
not merely a fixed event count. For illustration, gauge 2^-8..2^8 and 30 seconds
bound local prefix magnitude by 61,440 at speed 8; that magnitude alone does not
prove binary32 subtraction adequate.

With 32-event blocks, 20k events might yield 625 tree nodes, depth about 10.
Adversarial gauge changes can force singleton blocks, so this is not a stronger
worst-case guarantee. An uncached query is O(K+log B) without more endpoint indexing.
Storage appears feasible in marker data/shared banks, but requires a distinct
compiled ledger and extra local certificate logic.

Use this only if it improves measured style-switch frames enough to justify a
second level of indexing. It does not remove accurate ratio construction.

## D. Logs, symbolic factors and exact ratios

These are useful special cases, not preferred general replacements:

- Deterministically reusing log(speed) cancels repeated identical reciprocal
  endpoints. Compensated summation does not correct log evaluation error.
- Different endpoints can express an exact multiplicative identity without their
  rounded logs adding to zero. A concrete cycle is speeds 1.125, 1.375, 4.8125,
  3.9375, 1.125 with styles scroll, timescale, scroll, timescale. Since
  1.125*4.8125=1.375*3.9375, the true ratio is one. Rounded normalized endpoint logs,
  even summed exactly, leave about -8.20e-8 in log2 per cycle; 5,000 cycles give
  about -2.84e-4 relative ratio drift before exponentiation error.
- Separately multiplying numerators/denominators moves the rounding problem.
  Dyadic speed inputs have ratios with odd denominators; general exact products
  need unbounded integer/factor storage. That is a poor fit for Sonolus entity slots.
- Same-style runs really do telescope and should be simplified as in B. General
  alternating runs do not. Snapping small residuals to zero can erase real authored
  changes and is not a valid normalization rule.

The installed operation set exposes Log and Power, but no native frexp, ldexp or
FMA. A log-based normalization also adds runtime cost if not fully precomputed.
Use bounded power-of-two scaling helpers and test actual client arithmetic.

## E. Bake note trajectories or evolve one note-local state

An unrestricted note spanning L transitions has O(L) trajectory pieces. Precomputing
every note/event pair is possible mathematically but needs O(N*E) storage: up to
400 million pairs in the proposed envelope. More preprocessing time does not create
that storage. Watch note data is already full; private memory holds only a small
number of certified anchors once attachment caches are included.

Evolving one scalar forward from spawn is not a replacement. Different far-future
hits can initially differ by exponentially small distances; later scroll expansion
amplifies distinctions that the scalar already lost. Periodic recomputation from
immutable target metadata is necessary.

Bounded traversal stacks or a few baked right-boundary checkpoints can reduce
refresh cost. A full depth-15 stack of four-slot values uses 60 private slots before
keys/current fields. Four to eight levels fit better but leave occasional indexed
refreshes. This may be useful after profiling, not as an assumed O(1) universal fix.

## F. A bounded number of style switches

A promising scope cut is at most K style switches per group, retaining unlimited
same-style easing markers within the existing marker-count envelope. Trial K=8
allows at most nine runs, of which at most five are scroll runs.

At speeds 0.05..8, each complete scroll run ratio is bounded by 160, so a cross-run
ratio is bounded by 160^5 (about 1.05e11), and its reciprocal. With 1,802 seconds
of aggregate duration, B is bounded by 8*1802*160^5 (about 1.51e15). Both fit ordinary
binary32 range. This does not permit scalar global-prefix subtraction, but it can
eliminate extended-exponent arithmetic and a general run tree for the bounded tier.
Accurate run integrals and local queries are still required.

Count ordered zero-duration style operations too. A run may contain thousands of
speed/easing markers without introducing additional scroll-ratio factors. Cross-run
refresh is bounded by nine transfer applications rather than all E markers.

This is a more targeted performance restriction than removing all within-group
style changes. It is a proposed tier to benchmark, not an already accepted authoring
limit. A density/live-entity budget still matters even with few switches.

## Upfront visibility work

Retain conservative exact/interval search even when it is expensive upfront.
Do not enforce a small preprocessing deadline by spawning many objects earlier;
that trades acceptable loading work for the critical runtime cost.

For positive ordinary notes sharing a conservative distance ceiling U and judgment
point, there is an optional stronger optimization: sort by hit time and reuse a
chronological search cursor. For h2>h1>t, D(t,h2)>D(t,h1), so the earliest entry into
D<=U is nondecreasing with h. This remains true even when individual notes enter
and leave repeatedly. Search each target from the previous target's conservative
spawn, preserving the earlier cursor when uncertainty remains.

Total event advances are then O(E), plus per-note start/entry/refinement work;
distance-tree access gives a nominal O((N+E)log E) path. A common U may spawn some
notes early; bucket bounds only if that measurably reduces active entities.
Signed legacy and arbitrary attachments do not inherit this ordering theorem.

This optimization requires sorted group-note processing and separate target,
spawn and attachment/stage-finalization passes. It is optional under the high
preprocessing budget; do not destabilize existing initialization merely to reduce
loading time if generic per-note search is acceptable.

## Experiment order and decision criteria

1. Confirm actual storage/arithmetic precision and compile accurate preprocessing
   plus rounded-summary runtime applications. Check ordinary and non-dyadic stress
   histories; certificates must enclose reference values.
2. Add run-end caches and accurately precomputed run prefixes/suffixes. Measure
   steady frames, dense same-style markers, actual style-switch frames and seeks.
3. Compare unrestricted runs against the K=8-switch tier. Record scalar operation
   counts, p99/worst frame time, peak entities, memory and accuracy; loading time is
   reported, not capped by an arbitrary five-second target.
4. Prototype block-end caches only if style-switch cost remains material and users
   need unrestricted alternation. Compare against the simpler bounded tier.
5. Improve spawn precision/tightness upfront before considering early-spawn work
   limits. Optimize loading with the sorted sweep only if needed.

The recommendation is a staged measurable choice, not a claim that every candidate
fits the runtime budget. Normalization is practical and central; the exploratory
results rule out relying on normalization alone to erase arithmetic error.
