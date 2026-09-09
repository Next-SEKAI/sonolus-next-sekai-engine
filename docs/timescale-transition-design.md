# Timescale and scroll transitions: implementation and release specification

Status: final review changes, automated checks and full-engine compilation are
complete. Client release validation and timing/precision measurements remain pending.
This is the implementation and release specification for the [product proposal](timescale-proposal.md).
The contracts and gates below remain requirements, not claims that release validation
has passed. See [implementation validation](timescale-implementation-validation.md) for
the current evidence boundary. This replaces the earlier exploratory versions.

## 1. Scope and architectural decisions

Implement the feature entirely in Python, using the engine's own evaluator:

- Each timescale marker supplies the outgoing transition style: TIMESCALE or SCROLL.
- Both styles support NONE/held, LINEAR, IN_QUAD, OUT_QUAD, IN_OUT_QUAD and OUT_IN_QUAD.
- All-timescale groups preserve signed speeds, stops, reversals and existing skips.
- A group containing any SCROLL marker requires positive speeds and zero skips throughout.
- Existing data defaults to TIMESCALE. No fractional mix, independent scroll channel,
  serialized group mode, player override or initial style-switch limit.
- Integrate play, watch, attachment/connector/SimLine rendering, preview annotations,
  Python authoring helpers and engine schema documentation. No JS/SUS/USC work.

Runtime is the primary performance constraint. Spend preprocessing work on accurate
arithmetic, indexes, run-local coordinates and tight spawn times. Loading time is
measured, without an arbitrary short cutoff.

Commit to one architecture:

1. Preserve the original ordered marker links, including zero-duration links.
2. Build an immutable balanced transfer tree in those existing marker entities.
3. Identify maximal same-style runs without discarding internal easing markers.
4. Construct accurate aggregates and run prefixes/suffixes upfront.
5. Publish bounded scalar summaries for ordinary runtime queries.
6. Cache target values at run anchors in the evaluating consumer's private memory.
   Rebase adjacent anchors only while their propagated certificate meets the whole-run
   budget; otherwise reconstruct from the immutable tree.
7. Update each used group in its own early sequential callback, then prepare
   consumer-private caches; parallel rendering reads those caches.
8. Compute first visibility with conservative chronological search during preprocessing.

Do not add a second block/checkpoint index, a generic polynomial package, fractional
integration machinery or per-note/per-event trajectory tables. Those are alternatives
in [the exploration notes](timescale-approaches.md), not hidden requirements here.

## 2. Authored data and observable behavior

### 2.1 Schema

Define TransitionStyle in the shared timescale definitions:

| Value | Name |
|---|---|
| 0 | TIMESCALE |
| 1 | SCROLL |

Add marker import transitionStyle with default zero. Reuse EaseType from
sekai/lib/ease.py and explicitly import #TIMESCALE_EASE with that enum in play,
watch and preview. The library's StandardImport.TIMESCALE_EASE only admits the
old NONE/LINEAR enum.

Append transition_style after hide_notes in LevelTimescaleChange, preserving its
five existing positional arguments. Keep LevelTimescaleGroup's existing shape.
The builder and engine derive group classification by scanning markers.

| Data | Meaning |
|---|---|
| #TIMESCALE | Authored line speed; equals legacy timescale in an all-timescale group |
| #TIMESCALE_EASE | Outgoing easing, numeric values 0 through 5 matching EaseType |
| transitionStyle | Outgoing mechanism; default TIMESCALE |
| #TIMESCALE_SKIP | Legacy integral jump, converted by skip*60/BPM_at_marker |
| hideNotes | State exposed after the marker's complete timestamp batch |
| first / next | Authoritative chronological chain; chain order breaks equal-time ties |
| forceNoteSpeed | Preserve the current override and cover-compensation bypass |

A zero serialized skip is valid in hybrid groups. Any nonzero skip is rejected there.
Validate every marker, including held events, same-time links and the final marker.
A final SCROLL marker triggers hybrid validation even though its held tail has no
further speed change; this makes classification independent of dead-field optimization.

Builder-created groups retain the current rejection of an empty changes list.
Raw nonzero groups with first=0 remain valid identity groups.

### 2.2 Incoming versus outgoing ownership

A marker a controls the transition to its next marker b:

- Eased: interpolate from v(a) to v(b), using a's easing and style.
- NONE: hold v(a) until b, then change speed using a's style.
- A zero-duration timescale link installs the new speed directly.
- A zero-duration scroll link applies its speed ratio.
- Only after that incoming operation does b install its own outgoing properties.
- A legacy destination skip is applied at b after the incoming interval.

Never divide by the old speed in a signed/zero TIMESCALE transition. Never create
an epsilon-duration ramp. Timescale steps preserve position; scroll steps rescale
distance. Changing style with no speed change produces no position change.

Use implicit speed one, NONE easing and TIMESCALE style before the first marker.
After the final marker, hold the resulting state indefinitely. The final outgoing
tree link is identity with zero stored duration; its unbounded tail is evaluated
analytically rather than stored as an interval ending at infinity.

### 2.3 Ordered anchors and rendered timestamp states

Internally, an anchor is an ordered marker state (converted_time, chain_ordinal).
Each original marker is a distinct state, even when several share a timestamp.
Public locate_time(t) returns the **last** marker at or before t, so rendering and
note targets always observe the completed right state.

Runs may end at an intermediate state of a same-time batch. Keep that actual raw
anchor for transfer composition and cache keys. Do not substitute the batch's final
speed into a run formula. Intermediate states are mathematical anchors, not frames.

Example: hold speed 1 by timescale; at time 1, marker B sets speed 2 and has outgoing
SCROLL; same-time marker C sets speed 1. The transfer from t<1 to C is R=2, B=1-t.
The transfer to B alone has R=1. Runtime lookup selects C; any run ending at B must
leave B->C in the remaining range query.

Search tests complete timestamp states once. A zero-duration intermediate state,
or a left limit that exists only immediately before a jump, cannot by itself prove
visibility at the timestamp.

### 2.4 Identity, floor and validation

Reserve ref zero for a virtual pre-first locator, not an invalid-cache key:

- Group zero and raw empty groups evaluate h-t.
- Both times before the first marker use identity directly.
- A prelude query crossing the first marker composes its first skip/batch operations.
- A hit exactly at a timestamp uses the completed right state.
- Build from all authored markers, including pre--2 history. The playable/search
  floor remains MIN_START_TIME=-2; evaluate the actual curve there.
- Disabled timescale returns identity without table reads and ignores hiding.
  Forced note speed still applies to preempt.

Validate finite values, enum ranges, positive hybrid speeds, zero hybrid skips,
reference validity, declared ownership, cycles and nondecreasing converted times.
A missing marker ownership import may be treated as unspecified for legacy raw data;
a nonzero conflicting group reference is invalid. The chain-derived owner prevents
one marker from being silently reused by multiple groups.

Use per-marker validation_owner/state fields for bounded traversal. Invalid builder
data raises an actionable Python exception. Raw invalid groups receive an error code
and never become partially usable timelines. Calls requiring such a group use the
library's error path. debug.error terminates a callback, not necessarily the level;
do not describe it as host-level level rejection or replace invalid hybrid behavior
with timescale silently.

### 2.5 Compatibility policy

No new engine/replay revision solely for the optional field. Keep replay data and
judgment timing unchanged. Apply the following presentation fixes consistently to
play and watch, without maintaining a second historical evaluator:

- Consume all same-time markers for position and hiding.
- Use the same real curve at the search floor and afterward.
- Handle group zero/empty groups consistently.
- Replace the initial/crossing visibility-bound mismatch.

Record these fixes in schema/release notes and test existing replay fixtures. If
tests identify a scoring or replay-format dependency, resolve it before merging;
the intended change is presentation, not judgment semantics.

## 3. Mathematical kernel

### 3.1 Shared field

Let v be authored line speed, S scroll and T timescale:

~~~
A' = T
D(t,h) = S(t) * (A(h)-A(t))
progress = 1-D(t,h)/preempt
S*T = v
~~~

TIMESCALE holds S constant; SCROLL holds T constant. Factors conceptually persist
across style changes. Never reset actual scroll to one.

A coordinate normalization

~~~
A_new = c*(A-A_anchor)
T_new = c*T
S_new = S/c
~~~

preserves positions. Use immutable event/run coordinates and anchor references, so
normalization does not require rewriting all notes. Power-of-two scaling can change
units exactly in binary, but cannot recover information lost before normalization.

### 3.2 Exact easing and integration

For u in [0,1]:

| Ease | E(u) |
|---|---|
| NONE | Constant old value; endpoint change is separate |
| LINEAR | u |
| IN_QUAD | u^2 |
| OUT_QUAD | 2u-u^2 |
| IN_OUT_QUAD | 2u^2 for u<=1/2; 1-2(1-u)^2 otherwise |
| OUT_IN_QUAD | 2u-2u^2 for u<=1/2; 1/2+2(u-1/2)^2 otherwise |

Semantically v=v0+(v1-v0)*E. Evaluate positive curves using nonnegative endpoint
contributions and explicitly computed complementary easing. Falling ease-out uses
v1+(v0-v1)*(1-u)^2. Return stored endpoint inputs directly at exact endpoints.

On each quadratic piece:

~~~
integral[l,r] v = (r-l)*(v(l)+4*v((l+r)/2)+v(r))/6
~~~

This is exact polynomial integration, not adaptive quadrature. Split only at an
in-out/out-in midpoint crossed by the query. Handle zero duration and NONE before
any division. Derive short width directly from r-l with the chosen accurate
subtraction; do not recover it from two rounded normalized offsets. Calculate
midpoints in local coordinates, not as a large absolute time plus a tiny offset.

Same-event distance is integral[t,h] v for TIMESCALE, or v(t)*(h-t) for SCROLL.
The direct kernel remains the reference and exceptional accurate same-event path.
Ordinary runtime evaluation shares the current polynomial evaluation/integration
once per group per frame, then uses certified local run-coordinate differences;
there is no per-note easing evaluation on the successful ordinary path. These are
local accurate coordinates with an explicit cancellation certificate, not rounded
full-chart primitive subtraction. Signed legacy integration retains signed error
accounting. No fixed acceleration epsilon decides whether an event is constant.

### 3.3 Atomic transfers

For chronological anchors a<=b<=h:

~~~
D(a,h) = R(a,b)*D(b,h)+B(a,b)
R(a,b) = S(a)/S(b)
B(a,b) = S(a)*integral[a,b] T

then(L,Q) = (L.R*Q.R, L.B+L.R*Q.B)
~~~

L comes before Q; composition is not commutative.

| One outgoing link to its destination state | R | B |
|---|---|---|
| TIMESCALE | 1 | integral[a,b] v, plus the legacy destination skip |
| SCROLL | v(a)/v(b) | v(a)*(b-a) |

For NONE use the held speed in the timescale integral. The scroll ratio includes
the destination step. Zero-duration scroll links have B=0; zero-duration legacy
timescale links may still have a destination skip.

A partial suffix inside a positive-duration link has:

~~~
TIMESCALE: R(t,b)=1;         B(t,b)=integral[t,b] v
SCROLL:   R(t,b)=v(t)/v(b);  B(t,b)=v(t)*(b-t)
~~~

Add a legacy destination skip when that partial interval includes the destination.
Subsequent same-time links remain explicit. A helper requesting the completed
timestamp must compose through all of them.

The implicit first-marker operation is handled by the prelude helper, since it
does not have a real source marker. Never drop its legacy skip.

### 3.4 Runs and orientation

Partition outgoing links into maximal consecutive same-style runs:

~~~
TIMESCALE run: R=1;              B=integral v + included legacy skips
SCROLL run:   R=v_start/v_end;   B=v_start*duration
~~~

Run endpoint speed belongs to its actual ordered endpoint. Preserve internal
markers for easing, hiding and visibility. A complete homogeneous scroll subtree
can use the endpoint formula instead of multiplying all internal ratios.

Future cache: for target at or beyond finite run end b, cache D(b,h).
Then D(t,h)=R(t,b)*D(b,h)+B(t,b).

Past cache: for target at or before finite run start a, use positive magnitude
M(a,h)=-D(a,h) in positive hybrid groups:

~~~
M(t,h) = (M(a,h)+B(a,t))/R(a,t)
D(t,h) = -M(t,h)
~~~

For a general oriented interval, D(t,h)=-B(h,t)/R(h,t) when t>h.
Do not merely negate D(h,t). Keep ratios/division range-safe.

Same-run targets use the pure-run formula. Timescale run coordinates include skips;
scroll targets use v(t)*(h-t). Final open runs use finite start coordinates and
analytic held tails, never a cache at infinity. Legacy signed distances retain
signed values rather than using positive-magnitude assumptions.

## 4. Numeric representation and certification

### 4.1 Accurate construction, inexpensive publication

Use a four-slot AccurateScalar:

~~~
(hi, lo, exponent, error)
true value in [(hi+lo)-error, (hi+lo)+error] * 2^exponent
~~~

Define exact zero as all zeros. Normalize the leading mantissa to a bounded binary
range. Signed centers support legacy values, curve coefficients and certified
local differences. The nonnegative error is an absolute radius in the same units.
Hybrid transfer-ratio division requires a positive lower denominator bound.

Construct scroll ratios and every parent aggregate from accurate endpoint/child
values. An exponent alone fixes range, not mantissa drift. Building parents from
rounded child summaries would reintroduce O(E*u) factor errors.

A runtime PublishedScalar reads the stored hi and exponent with a radius including
abs(lo), construction error and any publication rounding. It needs no duplicate
persistent bank. Ordinary distance queries apply published transfers right-to-left:

~~~
x = R_node*x+B_node
~~~

They do not construct a combined R unless orientation requires it. Error then depends
on the small number of query applications, rather than all authored leaf divisions.

Retain accurate fields for cold cache refreshes if the published path cannot meet
the requested budget. Applying accurate arithmetic to previously rounded values
cannot recover their missing low components.

### 4.2 Required operations

Implement only normalized add, multiply, divide, compare, affine compose/apply and
bounded conversion, plus high/low signed add/subtract for legacy/run coordinates.
Do not require FMA. Use power-of-two normalization with bounded helpers; do not
materialize an enormous scalar to normalize it.

Multiplication error includes at least:

~~~
abs(x)*ey + abs(y)*ex + ex*ey + arithmetic_rounding
~~~

Addition, division, exponent alignment and conversion need corresponding conservative
bounds. The bound calculations themselves must round outward. If an aligned tiny
term is omitted, include its magnitude conservatively in the radius. Never clamp
separate factors or report underflowed error as exact zero.

Compile-test error-free transforms and normalization under the actual optimizer.
Treat native beat/time outputs as the quantized inputs to the reference comparison.
Do not assume Python float precision matches the client.

### 4.3 Why range is still needed

Alternating ordinary 1->2 timescale and 2->1 scroll can produce conceptual factors
2^n and 2^-n. For 20k transitions in [0.05,8], a conservative R exponent magnitude
is below 146,440. Over a stored span of 1,802 seconds, B is bounded by
8*1802*160^20000, exponent below about 146,454. Use the actual span for earlier
pre-floor markers. These exponent integers fit exactly in binary32-valued slots.

Visible local queries must not subtract full-chart prefixes. Positive hybrid
transfer sums do not cancel; signed legacy sums track absolute contribution and
have a separate supported-conditioning test.

### 4.4 Certify cache use, not only its anchor

An anchor's error may be amplified by the current scroll run. Before accepting a
cache, bound its use over the applicable run using maximum suffix/prefix ratios,
effective preempt and local-operation error. A boundary value accurate at b is not
automatically accurate for all t before b.

Use a total algorithmic visible-progress budget of 1e-4. Initial allocation for
implementation tests: 2e-5 to cached anchor uncertainty after amplification, 2e-5
to local speed/integral evaluation, 2e-5 to scalar affine application and progress
conversion, and 4e-5 reserve for signed/cancellation/geometry-sensitive cases.
These are absolute budgets; adjust their allocation only while preserving the total.

A cache refresh may use retained accurate metadata if scalar summaries fail this
test. Do that at run/target changes or preprocessing, not repeatedly on ordinary
frames. The same-run high/low subtraction is a small fixed-cost kernel, not a
general tree reconstruction.

Large offscreen values may remain scaled and be classified by bounds. Do not
independently clamp endpoint coordinates before connector/attachment interpolation.
An uncertified potentially visible value must not be replaced by a guessed float.

## 5. Concrete storage design

Use existing marker entities; no global event arena and no injected entities.
Current installed sonolus-py 1.2.1 limits are 32 imported/data slots, 32 shared,
64 private per entity and 4,096 slots per level-data/level-memory bank. Recheck
these in the compile gate; scalar counts are not client byte measurements.

### 5.1 Marker ledger

| Bank | Fields | Slots |
|---|---|---:|
| Data | Existing imports plus transitionStyle | 8 |
| Data | Event start/end times | 2 |
| Data | Balanced-tree left/right refs | 2 |
| Data | Subtree first/last ordinal | 2 |
| Data | Accurate subtree R and B | 8 |
| Data | Run first/end refs | 2 |
| Data | Style-specific run-prefix/scroll-ratio field and run suffix | 8 |
| **Data total** | | **32/32** |
| Shared | Accurate suffix bounds: R_min, R_max, B_max | 12 |
| Shared | Style-specific ratio/curve coefficient and accurate own outgoing B | 8 |
| Shared | Ordinal, previous marker, tree parent | 3 |
| Shared | Validation owner | 1 |
| Shared | Maximum authored speed in the run | 1 |
| Shared | Accurate converted destination skip | 4 |
| Shared | Split midpoint high/low components | 2 |
| **Shared total** | | **31/32** |

Each accurate value includes its error slot. Both marker banks are full. Access
style-specific fields through the documented accessors; these are explicit unions:

| Stored field | TIMESCALE meaning | SCROLL meaning |
|---|---|---|
| run_prefix (4 data) | B(run_start, marker) | R(marker, run_end), read by _scroll_run_ratio |
| run_suffix (4 data) | B(marker, run_end), including destination skips | B(marker, run_end) |
| ratio_or_curve (4 shared) | LINEAR slope or first-piece quadratic coefficient; NONE zero | Atomic full-link R |
| own_distance (4 shared) | Atomic B including destination skip | Atomic B |
| midpoint_hi / midpoint_lo (2 shared) | Split event midpoint for local polynomial evaluation | Retained split event midpoint |

TIMESCALE atomic R is exactly one and reconstructed by _atomic_transfer. Its
LINEAR slope is delta_speed/duration; the quadratic coefficient starts with
delta_speed/duration^2 and has factor 1 for IN, -1 for OUT, 2 for IN_OUT and
-2 for OUT_IN. The current piece chooses the appropriate endpoint/midpoint anchor
and sign. The split midpoint avoids losing a short interval to absolute-time rounding.

TIMESCALE run coordinates include destination skips and exclude a skip already
incorporated at the source. SCROLL run_prefix is a ratio, not a stored time/integral
prefix; runtime obtains B(run_start,now) analytically from elapsed time and start
speed. A final open run's stored ratio/suffix uses the final finite marker anchor;
its held tail remains analytic. Signed legacy suffix bounds reuse the three bound
records through mode-specific accessors.

A style-switch marker's fields belong to its outgoing run. The preceding run
obtains its endpoint total from that run's stored suffix/range aggregate, never
from the switch marker's reset prefix. Accessors must take the intended run and
ordered anchor explicitly. A final open run stores a finite suffix to the final
marker, with its held tail handled analytically.

### 5.2 Group ledger

Data: existing first/force-speed imports plus root, mode, validity, marker count,
final-marker ref, error code, used flag, cached effective_preempt and the
consumer-derived needed_start/needed_end bounds = **12/32**.

Shared: time-valid flag, last update time, current event/run refs, current_constant,
run-end ref, scalar current speed and hiding (8); certified current speed (4); four
AccurateScalar coefficients for future/past run-local applications (16); and the
preprocessing spawn cursor (last target, upper distance bound, conservative spawn,
valid flag: 4) = **32/32**. There are no spare group shared slots.

The group also uses an explicit style-specific union: future_ratio/past_ratio are
actual run suffix/prefix ratios for SCROLL. For TIMESCALE, future_ratio stores the
current quadratic coefficient (zero for LINEAR) and past_ratio stores midpoint
speed when OUT_IN needs it; TIMESCALE transfer application treats both ratios as
one. current_constant replaces the former redundant current_run_start field.

Layout.default_preempt is initialized once from user speed/cover settings. Each
group caches effective_preempt during preprocessing, including its forced-speed
behavior. Consumers read these cached values instead of evaluating the option
formula per note per frame.

All immutable tree fields are written during preprocess only. Group current
coefficients are written sequentially once per actual time; parallel callbacks
only read them.

### 5.3 Target and consumer cache

The former two-slot target_scaled_time has been replaced by the single-slot
TargetPosition(event_ref). Existing target_time supplies the exact quantized hit
time, and preparation reconstructs its local coordinate from the immutable
event/time. The unused local_value slot was removed, saving one note data slot.

A nine-slot TrajectoryCache contains:

- target entity ref;
- current run ref;
- kind: IDENTITY/PRELUDE/SAME/FUTURE/PAST;
- anchor ref;
- AccurateScalar value (four slots);
- valid flag.

The target entity supplies immutable group/time. Ref zero is a legitimate virtual
anchor; validity is explicit. SAME stores a target run coordinate, FUTURE stores
D(run_end,h), and hybrid PAST stores -D(run_start,h).

| Consumer | Other private slots | Caches | Diagnostics | Total private slots |
|---|---:|---:|---:|---:|
| Play note | 4 | 2*9 | 2 | **24/64** |
| Watch note | 1 | 2*9 | 2 | **21/64** |
| Play connector | 1 | 4*9 | 2 | **39/64** |
| Watch connector | 0 | 4*9 | 2 | **38/64** |
| Play / watch SimLine | 0 | 4*9 | 2 | **38/64** |

The two diagnostic fields count accurate refinements and uncertified visible results.
Each note also stores a native_progress_certified boolean: preprocessing proves
the simple constant-speed formula over its complete visible/offset envelope.
This flag does not certify a nonconstant run-coordinate subtraction.

Two note caches cover its own trajectory or its attachment head/tail. Four
connector/SimLine caches cover two potentially attached endpoints.

**The evaluating consumer owns the cache.** EntityRef access cannot read another
entity's private memory. Endpoint.progress reads were replaced with a target/
attachment evaluator taking the caller's caches explicitly. Keep immutable
target and attachment metadata cross-readable after despawn.

Slide-manager call sites were audited: their current visual-head helper reads
lane/size/mask geometry, not trajectory progress, so they need no added caches.
Their private use remains 14 slots in play and 12 in watch.

### 5.4 Scratch and traversal

There is no reserved 512-slot level arena. Validation constructs a rightward vine
in existing marker records; Day-Stout-Warren rotations balance it without a tree
build stack. Stored parent links support stackless postorder aggregate construction,
canonical range queries and chronological subtree exclusion.

Visibility uses callback-local arrays for up to four source trajectories/cubic
control records and a separate 64-entry Interval subdivision stack. That stack is
128 numeric payload slots plus its container bookkeeping; it is not a 64-slot
entity-private allocation. Compiler temporary storage and peak callback scratch
still require full-build measurement. The local solver checks available capacity
and returns the earliest unresolved interval with a diagnostic on exhaustion.
There is no combined tree-depth/local-subdivision stack and no parallel rendering
write to shared preprocessing scratch.

Verify the contiguous-range traversal visits O(log E) canonical subtrees rather
than repeatedly descending the same paths. Record actual visit counts.

Invalid node references fail structural validation. Exhausting implementation
workspace on a valid supported chart fails the implementation/release gate; it does
not make that authored group invalid or justify routinely spawning all notes early.

## 6. Preprocessing pipeline

Preprocessing uses explicit dependency bands in both play and watch. This replaces
the former same-order Initialization/DynamicStage dependency. There is no order-2
stage finalizer; stage lifetimes are extended directly by their consumers.

| Order | Work |
|---:|---|
| -4 | Stage/camera marker conversion and feature discovery, including stage-transform/dynamic-stage presence |
| -3 | Initialization: configuration/options/layout and existing global setup |
| -2 | Geometry-independent timescale build |
| -1 | DynamicStage list/setup and option-dependent derived geometry |
| 0 | Notes: idempotent basic metadata/target geometry, attachment geometry, then one visibility search per note |
| 1 | Connectors/SimLines: interior visibility, input/lifetime bounds and stage extension |

StageTransformChange sets LevelConfig.has_stage_transforms at -4, before
init_layout reads it for aspect locking and cover/hidden behavior. Initialization
indexes the camera list before initializing layout. init_level_config preserves
the discovered flags. DynamicStage converts beat-derived offsets only after layout
is ready. Beat/BPM access and other setup dependencies remain covered by
shuffled-entity and compiled callback checks.

Stage draw windows are authored from masks and remain distinct from extended entity
lifetimes. Earlier note/connector spawning extends lifetime, not the authored draw
window.

Within each timescale group:

1. **Validate/number links.** Walk the chain, assign ordinals and previous refs,
   cache converted start/end times, derive mode and final ref.
2. **Build atomic coefficients.** Compute accurate outgoing transfers including
   destination skips. Final stored link is identity. Prelude data remains implicit.
3. **Assign run boundaries.** Walk source styles in chain order, including same-time
   links. Populate run_first/end; the final open run has end ref zero.
4. **Build the balanced tree.** Balance the marker vine with Day-Stout-Warren
   rotations. Traverse parent links to build parents from accurate children and
   telescope homogeneous scroll subtrees.
5. **Build conservative subtree envelopes.** Retain signed/positive specialization.
   Intermediate states may widen a bound but must not become rendered points.
6. **Precompute run coordinates.** Compute accurate prefixes/suffixes; use balanced
   range evaluation or higher-precision replay if a linear accumulation's certificate
   is too wide. O(E log E) upfront work is acceptable.
7. **Initialize current-state cache invalid.** No dependency on which note asks first.

No group resets another group's persistent storage. Markers' existing imported
chain is retained; preprocessing adds indexes rather than rewriting authored order.

Note init_data() is idempotent metadata/geometry setup: it locates the target,
computes stage-dependent offsets/extents, and links notes. Target lookup alone
does not activate a group. It does not search visibility. Each note preprocess initializes its own
and attachment endpoints' basic data, applies attachment geometry, then performs
its visibility search once. Successful preprocessing registers actual consumer
windows after final starts/ends are known, before publishing the finite start.
Initializing an endpoint for another consumer therefore does not duplicate its
search, activate an otherwise unused group, or overwrite finished target geometry.

## 7. Runtime APIs and update ownership

Use a small explicit API:

~~~
locate_time(group, time) -> completed-state event ref
locate_target(group, hit_time) -> TargetPosition(event_ref)
register_group_window(group, start, end) -> extend group lifetime during preprocessing
register_note_group_window(note, start, end) -> register hide/attachment source groups
prepare_group(group, now) -> shared run-local coefficients
try_prepare_trajectory(group, hit_time, target, cache, now, target_ref) -> ready flag
complete_trajectory_refresh(group, hit_time, target, cache) -> complete pending cold query
prepare_trajectory(group, hit_time, target, cache, now, target_ref) -> compatibility wrapper
evaluate_trajectory(target, now, consumer_cache) -> certified distance
note_progress_value(note, first_cache, second_cache, now) -> certified attachment-aware progress
note_visual_progress_value(note, first_cache, second_cache, now) -> certified visual progress
distance_to_progress(distance, force_speed) -> scalar progress
first_visible_result(sources, progress_min, progress_max, earliest, latest) -> SpawnResult
first_visible(sources, progress_min, progress_max, earliest, latest) -> conservative spawn time
~~~

try_prepare_trajectory handles cache hits, classification and certified adjacent
rebases. A false result leaves cache.valid false, current target/run metadata and
the publication allowance temporarily in value.hi; the other value fields are not
readable trajectory data. complete_trajectory_refresh performs the pending query
and publishes a valid cache. Consumer batching consolidates only unresolved cold
requests; every request must complete in the same sequential callback before
parallel rendering. Ordinary hits and accepted rebases enter no dispatch loop.
prepare_trajectory preserves the direct try/complete wrapper for other callers.

A pure stateless distance query remains available for preprocessing/reference/
exceptional cold paths. It must not become the default endpoint property in hot
rendering loops.

### 7.1 Sequential preparation

locate_target() creates immutable target metadata without activating a group.
Actual notes, connectors and SimLines register their final preprocessing lifetime
windows through register_note_group_window; connectors also register the segment
head's hide-state group. Registration includes the note's own hide group and both
attachment source groups, even when those source notes are inactive anchors or
have already despawned. Standalone anchor metadata creates no demand by itself.
Group reference zero, disabled timescale and invalid/nonfinite windows do not
activate a group. A referenced raw empty group can still have a registered window.

For each valid used group, needed_start is the earliest registered consumer start
and needed_end is the latest registered end. This is a single bounding union of
consumer windows: gaps inside it are not tracked separately. Unused groups do not
spawn or run a per-frame evaluator. Used groups spawn with their consumer interval
and call prepare_group at sequential order -3, before all consumer preparation.

Play updates the group on the first frame that overshoots needed_end, then marks
it for despawn. Notes/SimLines can still prepare on that final frame before their
parallel cleanup; even a large time jump therefore sees current group state.
Watch exposes the same bounded union as spawn_time/despawn_time, allowing host
seeks to reactivate the group when returning to a needed interval. Unused watch
groups expose an empty interval at the sentinel time. Partial-replay consumers
may legitimately extend their union to the existing replay lifetime sentinel.

Consumer sequential callbacks prepare only their private caches after the group
update: connectors at -1 and notes/SimLines at the default order. The preparation
entry points check current group time/run identity. Group evaluation is not
inlined lazily into every consumer, and a reference to an endpoint's metadata is
not sufficient by itself to keep that endpoint's source group active.

Parallel drawing reads group coefficients and consumer-private caches; it never
prepares a group or refreshes a target anchor. Owner-private diagnostic counters
may be incremented during rendering. Source-private memory remains inaccessible.

A bounded small forward marker walk is a fast path; after a skipped frame or seek,
fall back to rightmost-time tree lookup. Never replay thousands of markers merely
to find the current event.

### 7.2 Cache refresh rules

Cache identity includes target, current run, kind and anchor. Internal easing-marker
changes preserve the run cache. Same-run seeks preserve immutable values but refresh
time-dependent group coefficients. A frame skipping several runs refreshes once to
the final current run.

For a hit beyond the run, query/cache D at the raw run end. For a past target, cache
at the finite run start with the correct signed/positive-magnitude convention.
For a same-run target, cache its accurate coordinate. Ordinary TIMESCALE queries
subtract the group-shared current coordinate with a certificate, including within
one event; exceptional accurate same-event evaluation retains the direct kernel.

Use ordinal-aware anchor eligibility, not time comparison alone, at equal timestamps.
Final tails never create future caches at infinity.

Certify the cache for its future use over the run before accepting the cheap
published path. Retained accurate fields provide a cold refresh if necessary.
Measure refresh frequency and accurate-fallback frequency separately.

For an adjacent run change, an existing future anchor may become the new run's
start, or a past anchor may advance by one run. Rebase its four-field AccurateScalar
using the immutable run B and stored SCROLL ratio: future values use (C-B)/R;
past magnitudes use (C+B)/R. Future-to-SAME can reuse the existing coordinate when
its meaning matches. Propagate the full arithmetic/input interval, including any
subtraction cancellation, and accept only if its error fits the allowance for all
uses over the new run. The allowance includes maximum within-run scroll amplification
and cached effective preempt.

If the certificate fails, or an anchor is ineligible after a seek/skipped runs,
query the immutable tree again (published first, retained accurate data if needed).
Same-run seeks preserve immutable anchors; a seek landing on an eligible adjacent
anchor may use the same certified rebase. Arbitrary/backward seeks do not replay
history to advance a cache. Every accepted rebase must pass the current bounded
error test, preventing unchecked accumulation of drift. This is consumer cache
rebasing at run boundaries, not a per-frame rolling group coordinate or mutation
of preprocessed tree/run data. Automated rolling/cache operation results are recorded
in the validation note; named-client switch/seek measurements remain pending.

### 7.3 Frame work

Let C count underlying trajectories queried by consumers, including repeated
attachment endpoints; it is not merely the visible note count.

| Case | Expected work |
|---|---|
| Same event/run | O(G+C), bounded exact local math and cached applications |
| Internal easing-marker changes | O(G log E+C) worst lookup case; note caches survive |
| Actual style-run changes | O(G log E+C) for accepted adjacent rebases; O(G log E+C log E) on cold resets |
| Arbitrary seek | Same worst case; same-run cache hits retained |

For distance-only future range queries, apply canonical subtree transfers right-to-left
rather than first constructing a combined transfer. For past targets, use the proved
positive-magnitude orientation or preserve R/B until division. The only rolling
optimization is the certified adjacent-anchor rebase above; never accept an
unbounded forward-evolved state without propagating and checking its error.

Do not promise O(1) arbitrary history with fixed storage. Measure actual style-change
frames, cold cache frames and attachment-heavy workloads.

Ordinary note drawing has two native scalar paths. Identity/constant formulas can
use the preprocessing uniform certificate boolean. SAME-TIMESCALE run-coordinate
differences still calculate their native high/low-pair certificate per evaluation;
there is no precomputed uniform flag for that path yet. Uncertain potentially
visible results retain the accurate fallback. Endpoint/attachment consumers retain
scaled values for interior cancellation and do not independently clamp endpoints.

Progress-probe operation counts on identical comparison fixtures are currently:

| Progress probe | Current VM operations | HEAD VM operations |
|---|---:|---:|
| Ordinary identity note | 46 | 46 |
| Ordinary grouped constant note | 76 | 61 |
| SAME-TIMESCALE native prefix difference | 223 | Not reported |
| SAME-SCROLL with varying speed/internal marker crossings | 159 | Not reported |
| FUTURE mixed-style affine application | 250 | Not reported |

These are VM operation counts for the compared progress fixtures, not whole-frame
or client timings. They exclude any claim that the <1ms or <=5% frame gates have
passed. Group curve work occurs once per frame. The preceding snapshot passed
full-engine compilation and automated rebase probes; the final review changes need a new build/validation run.
Named-client timing/precision and peak-scratch measurements remain pending. See the validation note for probe context, cold batching
costs and the remaining expensive far-target reset path.

## 8. Spawn and geometry

### 8.1 One visibility contract

The former helper's crossing thresholds and initial test disagreed. The current
helper uses one geometry-derived conservative region and preserves the requested
generous early-spawn leniency: progress bounds are at least [-3,6], expanded by
any broader draw guard and the full stage-pivot offset hull. For progress bounds [p_min,p_max] and
preempt P, distance bounds are [P*(1-p_max), P*(1-p_min)].

Account for visual_progress=progress-offset before conversion. Include the actual
draw guards, cover/tilt, supported offsets/elevation/transforms and relevant extents.
Keep visibility tightness distinct from numerical distance accuracy.

Current note speed 1..12 and Layout.approach_start clamped to 0..0.99 imply an
effective preempt range down to approximately 0.0035 seconds under fixed-only cover
compensation; forced speed bypasses that compensation and bottoms at 0.35.
Use the actual settings, not an assumed universal 0.35, in error amplification.

Do not use hideNotes to postpone spawning. Do not use a fixed lookback derived from
minimum speed: alternating styles invalidate the fixed-mix horizon theorem.
Search from the actual -2 floor. If the conservative geometry includes judgment,
ordinary first entry is no later than h, even if the entity remains alive afterward.
Other geometry needs a separately oriented post-hit domain.

### 8.2 Chronological enclosures

For a positive hybrid subtree ending before the hit, let its suffix bounds be
R in [R_min,R_max], B in [0,B_max], and enclose D_end:

~~~
D(subtree,h) is contained in
[R_min*D_end.lower, R_max*D_end.upper+B_max]
~~~

Timescale leaf bounds use its positive integral and R=1. Scroll leaf bounds use
speed extrema and B<=v_max*duration. Compose suffix envelopes for L then Q:

~~~
suffix_R = hull(Q.suffix_R, L.suffix_R*Q.full_R)
suffix_B = hull(Q.suffix_B, L.suffix_B+L.suffix_R*Q.full_B)
~~~

The positive specialization can discard B_min in favor of zero. Legacy signed
bounds use primitive extrema at timescale zeros, event boundaries and skip sides.

Atomic anchor envelopes can include intermediate batch states conservatively.
Actual visibility classification may only accept continuous intervals and completed
right states, not those internal anchors.

Traverse earliest first. Prune only proven exclusions. Refine within the at-most-two
quadratic pieces; the resulting distance is cubic at most. Use bounded bisection/
interval subdivision, with optional stable derivative-extrema isolation if it
meaningfully tightens preprocessing. No cubic radical formula.

### 8.3 SpawnResult

Return conservative_spawn, status, entry bracket and uncertainty reason:

- NO_ENTRY: all relevant intervals and actual boundaries excluded.
- VERIFIED_ENTRY: an actual visible point/boundary exists, with earlier time excluded
  except the returned entry bracket.
- POSSIBLE_ENTRY: earliest unresolved interval remains; return its start.

A tangency may have no sign change. A jump can enter or skip the region without
equaling a boundary. A contact that exists only as a left limit is not a visible
state at the jump. Test these separately.

Trial time resolution: max(0.25ms, the conservative client clock spacing). Round the
spawn toward an earlier representable time. Refine arithmetic accuracy before
accepting a broad uncertainty interval. Spend upfront work rather than imposing
a small visit cap that makes runtime entities spawn unnecessarily early.

Keep finite structural limits and diagnostics, but treat exhausted normal-chart
search as a failed release gate. Once spawned, an entity stays alive through
departures/reentries until its ordinary judgment/watch/connector despawn.

### 8.4 Attachments, connectors and SimLines

Preserve the existing attachment phase change: head progress clamps after its hit,
then interpolation fractions change. Cross-group attachments require both endpoint
timelines and their head-hit partition. They are not a single cubic trajectory.

Bound the rendered interior of connectors, including presentation modes, active/
inactive segments, stage/elevation transforms and through-judgment extension.
Endpoint minima alone are not a general visibility proof.

SimLine visibility must follow its actual implementation: it rejects endpoints
straddling judgment, clips progress, and fades to zero at sufficiently large
progress difference. Do not apply a generic opposite-side-segment example without
respecting those guards. Reproduce actual clipped/faded line fixtures.

Where a finite supported geometry envelope cannot be proved, record an exceptional
-2 fallback for that object. It must not be the common path. Do not clamp large
endpoint values independently before evaluating interiors.

Preserve play's input-window minimum, replay/partial replay lifetimes, connector
active intervals and through-line delay, SimLine endpoint/replay end rules, and
existing stage lifetime margins. Partial-replay notes may remain alive to 1e8;
ordinary watch despawn-at-hit is not a universal assumption.

### 8.5 Guarded preprocessing cursor

The implementation includes a small cursor fast path for one unclamped source in a
positive hybrid group whose conservative distance region contains zero. For a
nondecreasing hit time and an unchanged or smaller upper distance bound, the last
conservative spawn is a valid lower search bound. Group shared storage records
that target/bound/spawn and validity; decreasing targets or ineligible geometry
restart at -2. No global note sorting pass or per-note trajectory table is added.
Cross-group/attached/signed paths retain the generic chronological search.
This is an optimization of the same visibility contract, not a fixed lookback.

## 9. Module/file changes and migration

| File/module | Responsibility |
|---|---|
| sekai/lib/timescale_math.py | Stable easing, exact integration, AccurateScalar/publication/certificates |
| sekai/lib/timescale.py | Style enum/protocols, validation, atomic index, runs, query/cache orchestration |
| sekai/lib/timescale_visibility.py | Enclosures, chronological search and SpawnResult |
| sekai/lib/layout.py | Distance-to-progress; retain unrelated chronological callers |
| sekai/lib/note.py | Note drawing and geometry-aware spawn entry point |
| sekai/lib/timescale_consumer.py | Owner-private cache preparation, attachment evaluation, visibility sources and diagnostics |
| play/watch timescale.py | Imports, record layouts, consumer-bounded group lifetimes and early sequential updates |
| play/watch initialization.py, dynamic_stage.py | Explicit preprocessing order; preserve draw/lifetime distinction |
| play/watch note.py | One-slot target, geometry-before-spawn, consumer window registration and two owner-private caches |
| play/watch connector.py and sim_line.py | Four owner-private endpoint caches, interior visibility and lifetime extension |
| slide-manager Python call sites | Audit implicit progress reads and give actual evaluating owners caches |
| sekai/level_utils.py | Append style field, stable ordering/validation, marker serialization |
| sekai/lib/converter.py | Preserve legacy Python conversion defaults; no new external format work |
| sekai/preview/timescale.py | Import style/ease and annotate the selected chronological group |
| docs/level_data.md | Schema/defaults/restrictions/boundary semantics and compatibility fixes |

Preview must not suppress a meaningful outgoing style/ease merely because speed is
one at a nonpositive beat. Keep selected-group and chronological positioning behavior.
Use available text/print facilities; avoid changing preview note geometry.

The play/watch caller migration removed old accumulated-clock APIs. Regression audits cover
group_scaled_time, group_time_to_scaled_time, both inverse helpers, CompositeTime,
get_visual_spawn_time and progress_to; retained chronological helpers no longer use
accumulated group clocks. iter_timescale_changes_in_group_from_time remains available
for connector/SFX behavior, with completed-state hiding and iteration semantics
requiring regression coverage.

Do not grow the existing layout or note module with generic numeric machinery.
Keep shared numerical code independent of archetypes/options and play/watch wrappers
behaviorally identical.

## 10. Dependency-ordered implementation packages

These packages describe implementation responsibilities and their required acceptance
criteria. Code for the packages is present, but this list is not a completed-release
checklist: the final review changes passed the full build and focused checks.
Client confirmation of supported-envelope behavior, peak scratch and performance
gates remains pending.

### P0 — Contract and baseline fixtures

Deliver the enum/schema definitions behind disabled exposure, semantic golden fixtures,
and baseline render/score/compile measurements. Freeze atomic anchor ownership,
classification, identity/floor/final behavior and callback order.

Acceptance: all explicit boundary cases have expected outcomes; positional Python
APIs and old omitted fields serialize identically. No JS change.

### P1 — Independent oracle and exact local kernel

Add a Decimal/high-precision oracle from original marker inputs, independent direct
chronological composition, and analytic polynomial/rational cases. Implement production
speed/integral/atomic transfer kernels.

Acceptance: all easings, NONE, zero duration, signed roots/skips and local orientation
match the oracle. Same-time run endpoints are covered. Test quantized inputs separately
from original authoring precision.

### P2 — Compile/storage and arithmetic feasibility

Define actual marker/group/target/cache records and compile their access paths. Implement
accurate construction, outward error operations and published summaries. Verify optimizer
behavior and operation/storage rounding.

Acceptance: every slot ledger fits, scratch stays inside level capacity, cross-entity
private reads are absent, and 20k non-dyadic/huge-exponent cases meet certificates.
Run the real compiler, not only Python Record mocks.

### P3 — Immutable tree and run preprocessing

Implement validation, atomic ordinals, balanced tree/parents, run boundaries, accurate
subtree bounds and run prefix/suffix construction. Add identity/prelude/final handling.

Acceptance: random subranges and coalesced runs match uncoalesced oracle transfers;
parents never use rounded published children; lookups return final same-time states.
Prefix/suffix/run errors remain within their allocated bounds.

### P4 — Shared runtime evaluation

Implement group preparation, nine-slot owner caches, exact SAME paths, FUTURE/PAST
anchors and read-only evaluation. Add operation counters in a development build.

Acceptance: dense same-style markers preserve note caches; run switches refresh once;
same-run seeks retain immutable values; every referenced endpoint group is prepared.
No normal hot-path tree query or high-precision reconstruction.

### P5 — Notes, geometry and spawn

Migrate play/watch ordinary notes and attachment evaluation, order geometry before
visibility, implement signed/positive spawn search, then integrate connector/SimLine
interiors and consumer cache ownership. Preserve input and stage lifetime rules.

Acceptance: no late spawn against independent fixtures; no false visible microstates;
input/replay behavior unchanged; actual draw guards agree with bounds; no routine
early-spawn shortcut on the representative corpus.

### P6 — Python surface and preview

Expose transition_style, validate builders/raw data, update preview annotations and
schema docs, remove old conversion helpers after the call-site audit.

Acceptance: raw and Python-built charts agree; old positional/default behavior remains;
preview displays equal-speed nondefault markers; no new external converter scope.

### P7 — Runtime and accuracy release gates

Run full relevant regressions and named-client measurements. Record frame breakdown,
cold/run-switch costs, certificates, peak entities, compile/storage and loading work.
Resolve any failure without silently changing chart semantics.

Acceptance: all supported-envelope tests meet the accuracy and runtime requirements
below. There is no automatic style-switch restriction; a scope reduction requires a
separate measured product decision.

The Python authoring API and demonstration level are available in the development
implementation. Release remains gated on numerical/access feasibility and the full
validation sequence above; API availability is not a claim of release readiness.
Do not retain two competing production evaluators after migration.

## 11. Tests, fixtures and measurements

The test names below are responsibilities. Current coverage also uses
test_timescale_consumers.py, test_timescale_render_clipping.py,
test_timescale_geometry.py, test_timescale_stage_order.py,
test_timescale_authoring.py, test_timescale_demo.py and test_timescale_compiled.py.
Optimized probes execute through tests/timescale_vm.py; they model arithmetic and
do not substitute for a full client run.

### 11.1 Test organization

Add focused files rather than one implementation-mirroring test:

| Planned test | Focus |
|---|---|
| tests/timescale_reference.py | Independent high-precision oracle and input fixtures |
| tests/test_timescale_math.py | Easing/local integrals/transfers/orientation |
| tests/test_timescale_numeric.py | Certificates, publication, range, rounding and signed conditioning |
| tests/test_timescale_timeline.py | Validation, tree/runs, atomic ties, prelude/final and query order |
| tests/test_timescale_runtime.py | Cache ownership, preparation, seeks, same-style cache reuse and slot layouts |
| tests/test_timescale_visibility.py | First entry, tangencies, steps/skips, bounds and uncertainty statuses |
| tests/test_timescale_integration.py | Play/watch, attachments, connectors/SimLines, stages, options and preview |
| tests/test_level_compatibility.py | Positional/default/replay/schema regression additions |

Use actual engine functions with lightweight proxies where appropriate, plus compiled
kernel execution for numeric/access constraints. Do not treat a Python mock's float
behavior as a client certificate.

### 11.2 Mandatory cases

- Every ease/style with increasing, decreasing, equal and near-equal endpoints.
- Same-event, same-run, cross-run, prelude, raw empty, final-tail and post-hit queries.
- Same-time batches containing multiple alternating zero-duration links; run ends
  inside batches; left-limit-only contact; complete-state D(h,h)=0.
- Legacy zero/reversal/stop/positive and negative skips, including first-marker skips.
- Ratios 160 and repeated non-dyadic reciprocal identities; 20k transitions; huge
  exponents; all nodes and published/cache values enclosing the oracle.
- Dense same-style markers without cache invalidation, dense style switches, skipped
  frames, arbitrary seeks and same-run seek reuse.
- Max within-run cache-error amplification; smallest effective preempt and ordinary
  beat-derived visual offsets under cover compensation.
- Group zero, disabled timescale/hiding, forced note speed and malformed references.
- Multiple entry/reentry, tangency, jump into/over region and no-entry classification.
- Attachments across groups, head-hit phase change, inactive anchors/despawned endpoints.
- Actual connector presentation/clipping and SimLine judgment/fade guards.
- Play/watch/autoplay/replay/partial replay, chronological preview and stage lifetimes.
- Shuffled raw entity order, builder/raw parity and stable same-time ordering.

### 11.3 Supported test envelope

Target 30-minute charts, 20k markers and 20k notes, hybrid speed 0.05..8 and all
supported options/eases/styles. Test 1/4/16 active groups and 1,000 active notes;
count consumer trajectories C separately. Include representable-millisecond ramps
and clustered events. Use 64 groups/50k notes as overload probes.

Legacy stress uses speeds [-8,8], stops/skips and recorded absolute variation,
initially up to 1e6 scaled seconds. Inputs beyond the practical envelope retain
their semantics without an unlimited new precision promise. Arbitrary authored
10000x speed is not a release requirement.

### 11.4 Accuracy and runtime gates

| Gate | Required evidence |
|---|---|
| Visible algorithmic progress | <=1e-4 absolute at identical quantized input times |
| Positive speed evaluation | <=1e-5 relative |
| Certification | Oracle enclosed by accurate nodes, published summaries, query/cache and final visible result |
| Spawn | Never late under uncertainty; report bracket width/early margin and reason |
| Legacy frame regression | Trial <=5% p99 versus current engine on representative charts |
| Timescale frame work | Trial <1ms p99 at 1k active notes on named reference clients; report C and group count |
| Run-switch/seek frames | Separate p95/p99/worst measurement, not hidden by steady averages |
| Cache/precision fallback | No routine reconstruction on ordinary frames; cold accurate refresh frequency recorded |
| Entity cost | Representative corpus has no work-limit-driven early spawn; overload cases report peak live entities |
| Preprocessing | Record time/work/memory; generous upfront budget, no arbitrary five-second gate |
| Build | Full engine compiles within data/shared/private/scratch limits |

Trial timing thresholds become release criteria only with named low/midrange clients,
fixed build options, warm-up and repeatable fixtures. Profile speed/easing lookup,
cache preparation, affine application and drawing separately.

Binary32 time spacing near 1800s is 0.0001220703125s. At constant speed 8 and
preempt 0.35, that alone is about 0.00279 normalized distance per clock step;
smaller preempt and scroll ramps can amplify it further. Compare algorithm error
at identical quantized inputs and report clock/authoring quantization separately.

The [Engine ROM format](https://wiki.sonolus.com/engine-specs/resources/engine-rom)
is single precision, which does not prove every runtime operation has that precision.
Measure actual operation/storage behavior and compile optimizations before claiming
a client guarantee.

Run appropriate targeted tests throughout, then:

~~~
uv run python -m unittest discover -s tests
uv run sonolus-py build
~~~

Run Ruff/type checks appropriate to changed Python files. Preserve user-owned working
changes and existing tests; no unrelated cleanup or JS build steps.

## 12. Review disposition and remaining measured gates

Design and implementation reviews checked the scope against the Python source. Incorporated:

- Ordered internal anchor states versus completed public timestamps.
- Run-level future/past/same eligibility, cache-error amplification and certified
  adjacent-anchor rebasing with immutable-tree resets.
- Actual marker ledger: 32 data/31 shared; group ledger: 12 data/32 shared,
  with explicitly documented style-specific union fields and cached preempt.
- Consumer-private cache/diagnostic totals and stackless tree construction, without
  the former reserved-arena proposal.
- Nine-slot caches owned by consumers, not referenced endpoints.
- Consumer-derived group lifetimes, including hide and attachment sources; unused
  groups do not spawn. Play refreshes the final overshoot frame and watch uses
  bounded seek-reactivatable intervals.
- Used groups update at sequential order -3 before consumer-private preparation;
  one-slot target metadata does not activate them, and geometry-only note
  initialization is followed by one visibility search.
- Accurate construction and published summaries, with no rounded-child tree build.
- Stage feature discovery before layout initialization, then option-dependent stage
  setup; removal of the nonexistent stage-finalizer assumption and preservation of
  authored draw windows.
- Stackless chronological tree traversal, with a separate local-solver depth budget.
- Actual SimLine guards, smallest effective preempt and partial-replay lifetimes.
- Direct same-event math, rightmost lookup, finite final-tail anchors and raw identity groups.

The remaining gates require implementation/client measurement, not additional product
features: optimizer-safe arithmetic/certificates, actual compiled field sizes, geometric
envelope completeness, and runtime cost at style switches. They remain release
requirements in P2/P5/P7 even though the development authoring API is available.

Existing [basic](timescale_numeric_probes.py), [binary](timescale_binary_probes.py)
and [alternative-mesh](timescale_mesh_probes.py) probes are exploratory evidence.
In the binary probe, accurate high-precision subtree construction followed by rounded
runtime summaries produced approximately 1.5e-8 to 1e-7 relative B error in the tested
20k-transition queries. These observations motivate the design; they do not replace
the compiled certificate or client acceptance suites.
