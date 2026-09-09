# Timescale implementation validation

Status: review fixes, focused checks and the final full-engine build are complete.
Client release validation remains pending. No client timing, loading-time
or memory measurements are available.
The [release specification](timescale-transition-design.md) retains all accuracy,
visibility and performance gates.

## Implementation inspected

- Binary outgoing styles and six easings, raw timeline validation, signed legacy
  behavior and positive skip-free hybrid groups.
- Marker-backed balanced transfer tree, same-style run coordinates, retained
  accurate aggregates and published runtime applications. Adjacent consumer anchors
  may rebase through an immutable run transfer only when the propagated four-field
  certificate meets the budget over the entire next run; ineligible seeks or failed
  certificates reconstruct from the tree. There is no per-frame rolling group coordinate.
- Stackless Day-Stout-Warren tree construction; callback-local visibility work
  arrays and a separate 64-entry interval stack. No reserved level arena.
- Active groups update at sequential order -3. Current curve evaluation/integration
  is shared once per group per frame; ordinary note paths do not reevaluate easing.
  Consumer-owned caches prepare after groups without reading another entity's
  private memory. Layout.default_preempt and group.effective_preempt cache options
  and forced-speed/cover compensation during preprocessing.
- Idempotent note target/geometry setup precedes one visibility search. Consumers
  register group lifetimes for their own hiding state and attached source groups.
  Inactive anchors alone do not activate groups. Windows conservatively cover gaps
  between a group's first and last consumers; play includes the final cleanup frame.
- Shared visibility bounds preserve at least [-3,6] progress leniency plus complete
  stage-offset hulls. Attachments and connector/SimLine interiors are conservatively
  enclosed; actual render clipping remains responsible for final presentation.
- Python authoring, chronological preview annotations and the dedicated timescale
  demonstration level are present.

The inspected field layouts are marker **32 data / 31 shared**, group **12 data /
32 shared**, play/watch note private **24/21**, connector private **39/38**, and
SimLine private **38**. These counts include certificates and consumer diagnostics;
they are not client memory measurements. Full callback compilation passed separately.
The design records the exact style-specific unions for stored SCROLL ratios and
TIMESCALE curve coefficients. Each note's additional native-progress boolean
certifies its constant formula across the visible/offset envelope. SAME-TIMESCALE
high/low-prefix subtraction still computes a certificate per evaluation.

## Review corrections

- Internal scalar preconditions use `assert`. A compiled regression proves that
  release normalization has the same instruction tree as unchecked normalization;
  checked builds still reject invalid inputs. Authored-chart validation and
  accuracy fallback decisions remain operational checks.
- Uncertain attachment fractions enclose both branches of the legacy epsilon
  rule. Host and compiled near-tail tests show successful accurate refinement on
  either side of the threshold, without persistent visible-result failures.
- `VERIFIED_ENTRY` uses the original requested visibility bounds; outward search
  bounds still conservatively decide exclusion and spawn times.
- Group updates are bounded by consumer lifetimes. An already expired play
  SimLine also registers its endpoint groups for its final preparation/cleanup.
- Removed unused target/validation fields, obsolete update wrappers and superseded
  numerical kernels. Tests now exercise the production kernels. Comments explain
  cache coordinates, storage unions, rounding assumptions and lifecycle boundaries.
- Python requirements now match the existing 3.14 environment. Record operations
  and protocol constructors use `Self` where subclass preservation is intended;
  concrete factories retain concrete return types. Ruff and Pyright pass.

## Evidence and pending checks

Focused tests cover the high-precision reference, numerical kernels and certificates,
optimized numeric probes, timeline/consumer behavior, visibility, clipping, stage
geometry, authoring and the demonstration level. Numeric probes execute through a
local VM with explicit arithmetic models. Passing those probes does not establish
actual client arithmetic behavior. Full-engine compilation was checked separately.

Automated validation covers **179 passing feature tests**: all 171 non-stress tests
on the final sources plus eight practical-chart stress tests from the preceding
178-test review run. Subsequent cleanup removed unused state and added the SimLine
lifetime regression; the numerical kernels did not change. The stress tests include
all six 20,000-marker, 30-minute cases at preempt 0.0035. Native-scroll coverage
includes 72 enclosure cases and 12 guarded fallbacks across three precision/storage
models. Production and feature-test Ruff/Pyright checks pass. All 41 consumer
callbacks and eight group callbacks pass the compiler frontend; the final SimLine
preprocessing change was rechecked separately.

### Full build and artifacts

The final optimized build (`build sekai -O2 --gc`) completed successfully with
exit status zero in 1,810.36 seconds, compiling 140 callbacks across play, watch,
preview and tutorial.
It used a frozen source snapshot and a callback-timing wrapper around the standard
CLI. All 80 snapshot files match the final production sources. The generated mode
data and demonstration level were successfully decompressed and parsed.

| Artifact | Compressed bytes | Nodes |
|---|---:|---:|
| EnginePlayData | 6,783,603 | 976,029 |
| EngineWatchData | 6,568,511 | 938,558 |
| EnginePreviewData | 222,778 | 35,433 |
| EngineTutorialData | 57,782 | 9,246 |

Artifacts are under `.build/timescale-review/dist`; the compile profile and log are
`.build/timescale-review-profile.json` and `.build/timescale-review-build.log`.
The exported demo is 4,052 compressed bytes and contains 329 normal taps, 38
timescale markers and four groups. Play data is substantially larger than the
HEAD comparison build (388,309 compressed bytes / 58,830 nodes), largely reflecting
the preprocessing and accurate fallback implementation. This requires client
loading/memory measurement; it is not evidence of proportional runtime cost.
The compiler accepted all callbacks, but its profile does not report peak callback
scratch usage. No independent peak-scratch measurement is claimed.

The existing 96-test suite has the same 242 failing subtests and 16 errors as the
pre-change baseline, with no new failure/error identifiers. These are existing
elevation-demo and geometry expectations, not a clean full-suite result.

The independent rolling test covers 1,025 non-dyadic markers, 2,075 evaluations,
and 518 adjacent run crossings. It records zero adjacent cold resets and zero
hot-path tree queries; five seeks account for five of its six cold frames.
Additional signed tests use BPM 120, 137 and binary32-quantized 189.7. All retain
the strict `1e-4` certificate gate. Huge-exponent oracle checks use sufficient
Decimal precision to represent exact powers of two instead of relaxing enclosure.

A visibility-only host run over all 329 demo notes reached no work-limit fallback:
at most ten continuous cells and 36 refinements per note. Most entries returned
the normal conservative time-resolution bracket. This measures the search only,
not full client preprocessing or peak live-entity cost.

### Current progress-probe counts

Root integration compared the same ordinary-note fixtures against HEAD:

| Fixture | Current VM operations | HEAD VM operations |
|---|---:|---:|
| Identity | 46 | 46 |
| Grouped constant | 76 | 61 |
| SAME-TIMESCALE native prefix difference | 223 | Not reported |
| SAME-SCROLL, varying speed / internal marker crossings | 159 | Not reported |
| FUTURE mixed-style affine application | 250 | Not reported |

These are progress-probe operation counts, not frame times or client benchmarks.
They do not establish the legacy <=5% p99 frame gate, <1ms timescale-work gate, or
cost of all group/cache/geometry work. The original identity/grouped paths also
performed per-note preempt powers, which the new paths cache; counting every VM
operation equally does not model the relative cost of those native functions.
The isolated probes compile in a preprocessing callback context. In particular,
they retain group-validity guards that release frame callbacks can elide as
development assertions. Matched comparisons use the same context, but the counts
are not exact instruction totals for a complete production frame callback.

On the 20,001-marker near-target cache fixture, adjacent advancement fell from
6,725 to 853 operations before the final exact-power arithmetic optimization,
with no tree reads. The same cost at 513 markers demonstrates bounded successful
rebasing. Twelve consecutive pre-hit advances also avoided tree reseeding.
Far-target certificates can still force an expensive tree reconstruction. The
earlier dense ten-second-ahead fixture required about 34,100 operations on
advancement. This remaining cost must be included in client seek/switch and
attachment tests.

The final note-preparation comparison isolates cold batching using the same
current arithmetic and trajectory kernels on both sides:

| Path | Direct-wrapper helper | Shared cold completion |
|---|---:|---:|
| Steady hit | 44 | 43 |
| Accepted rolling update | 641 | 640 |
| Cold refresh | 6,183 | 6,207 |

Only unresolved cold requests enter the dispatch loop or copy caches. The extra
24 cold operations are not charged to ordinary hits or accepted rebases. This
comparison is not a historical pre-change bytecode comparison. Cache fixtures
use host preprocessing followed by binary32 storage; actual binary32 preprocessing
could produce larger certificates and additional accurate rebuilds.

After the review's assertion and unused-state cleanup, the actual note helper on
the 513-marker fixture measures **43** operations per steady hit, **613** per
accepted near-target advance, and **5,967** for the near-target cold fill. A target
ten seconds ahead costs **16,014** on advancement and **20,596** on cold fill.
These are the same isolated preprocessing-context, host-preprocessed/binary32-stored
probes described above. The native render table was remeasured and is unchanged.

Before release, record:

1. Peak callback scratch usage and client load/memory costs for the recorded build.
2. Client confirmation of the automated supported-envelope oracle/certificate
   results, including dense style switches, late-song times, smallest effective
   preempt, signed cancellation, clipping and repeated adjacent rebases/reset behavior.
3. First-visibility brackets, early margins, refinement/work-limit diagnostics and
   peak live entities. A conservative early fallback is not a performance pass.
4. Named low/midrange client results for steady and style-switch/seek frame times,
   precision, loading time and memory. Report clock quantization separately.

No runtime performance gate, representative-chart fallback gate or client precision
gate is claimed to have passed by this document.
