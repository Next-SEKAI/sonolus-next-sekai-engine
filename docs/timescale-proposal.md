# Proposed product: timescale and scroll transitions

Implement this entirely in the Python engine, using our own evaluator.

- **Per-transition style:** add an outgoing `transitionStyle` with `TIMESCALE`
  and `SCROLL`. Default to timescale, preserving existing charts. Authors can
  alternate styles within one group; there is no fractional mix slider.
- **Easing:** both styles support held/instant, linear, in-quad, out-quad,
  in-out-quad and out-in-quad. Ease the authored line speed in elapsed time.
  Style and easing belong to the transition to the next marker.
- **Supported charts:** all-timescale groups retain signed speeds, stops,
  reversals and existing skips. Groups containing scroll transitions require
  positive speeds and zero skips throughout. Do not add a separate group mode,
  independent scroll channel or player override.
- **Preprocessing does the heavy work:** normalize local coordinates, combine
  consecutive same-style transitions into runs, construct accurate cross-run
  transfer data, and compute conservative spawn times. Preserve every internal
  speed/easing marker. Normalization changes coordinates, never note positions.
- **Runtime stays small:** evaluate the current event once per group, then use
  cached note-local formulas. Refresh cross-run caches on style changes or seeks,
  not every speed marker. Prefer accurately preprocessed summaries over repeatedly
  applying expensive precision machinery during frame updates.
- **Consistent behavior:** integrate play/watch, attachments, connectors and
  SimLines; keep judgment timing unchanged and annotate chronological preview.
  Update Python authoring helpers and engine schema documentation only. No JS,
  SUS or USC work.

Release against explicit runtime and accuracy gates on practical charts, including
dense style changes. Spend additional preprocessing time to obtain accurate values
and tight spawn times rather than routinely spawning entities early. Keep loading
time measured, without imposing an arbitrary short deadline. Do not introduce an
unmeasured style-switch limit in the initial schema.

The [implementation plan](timescale-transition-design.md) contains the contracts
and validation work; [the alternatives review](timescale-approaches.md) explains
normalization and the runtime tradeoffs.
