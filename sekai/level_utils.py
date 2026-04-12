from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from sonolus.build.collection import Asset
from sonolus.script.archetype import PlayArchetype
from sonolus.script.level import Level, LevelData
from sonolus.script.timing import TimescaleEase

from sekai.lib.connector import ConnectorKind, ConnectorLayer
from sekai.lib.ease import EaseType
from sekai.lib.layout import FlickDirection
from sekai.lib.level_config import EngineRevision
from sekai.lib.note import NoteKind
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle
from sekai.play.bpm_change import BpmChange
from sekai.play.connector import Connector
from sekai.play.dynamic_stage import (
    DynamicStage,
    StageMaskChange,
    StagePivotChange,
    StageStyleChange,
    ZoomChange,
)
from sekai.play.initialization import Initialization
from sekai.play.note import NOTE_ARCHETYPES
from sekai.play.sim_line import SimLine
from sekai.play.timescale import TimescaleChange, TimescaleGroup


def _build_note_archetype_lookup() -> dict[tuple[NoteKind, bool], type[PlayArchetype]]:
    lookup: dict[tuple[NoteKind, bool], type[PlayArchetype]] = {}
    for archetype in NOTE_ARCHETYPES:
        is_fake = str(archetype.name).startswith("Fake")
        lookup[(archetype.key, is_fake)] = archetype
    return lookup


_NOTE_ARCHETYPE_BY_KIND = _build_note_archetype_lookup()

_SIM_LINE_EXCLUDED_KINDS = frozenset({NoteKind.ANCHOR, NoteKind.NORM_TICK, NoteKind.CRIT_TICK, NoteKind.HIDE_TICK})


@dataclass
class LevelBpmChange:
    beat: float
    bpm: float


@dataclass
class LevelTimescaleChange:
    beat: float
    timescale: float
    timescale_skip: float = 0.0
    timescale_ease: TimescaleEase = TimescaleEase.NONE
    hide_notes: bool = False


@dataclass
class LevelTimescaleGroup:
    changes: list[LevelTimescaleChange] = field(default_factory=list)


@dataclass
class LevelStageMaskChange:
    beat: float
    lane: float
    size: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStagePivotChange:
    beat: float
    lane: float
    division_size: float
    division_parity: DivisionParity
    y_offset: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStageStyleChange:
    beat: float
    judge_line_color: JudgeLineColor
    left_border_style: StageBorderStyle
    right_border_style: StageBorderStyle
    alpha: float
    lane_alpha: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStage:
    from_start: bool = False
    mask_changes: list[LevelStageMaskChange] = field(default_factory=list)
    pivot_changes: list[LevelStagePivotChange] = field(default_factory=list)
    style_changes: list[LevelStageStyleChange] = field(default_factory=list)


@dataclass
class LevelZoomChange:
    beat: float
    zoom: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelNote:
    beat: float
    lane: float
    size: float
    kind: NoteKind
    timescale_group: LevelTimescaleGroup | None = None
    stage: LevelStage | None = None
    direction: FlickDirection = FlickDirection.UP_OMNI
    is_fake: bool = False
    is_separator: bool = False
    segment_kind: ConnectorKind = ConnectorKind.NONE
    segment_alpha: float = 1.0
    segment_layer: ConnectorLayer = ConnectorLayer.TOP
    connector_ease: EaseType = EaseType.LINEAR
    attach: LevelSlide | None = None


@dataclass
class LevelSlide:
    notes: list[LevelNote] = field(default_factory=list)


type LevelEntities = LevelBpmChange | LevelTimescaleGroup | LevelNote | LevelSlide | LevelStage | LevelZoomChange


def _note_archetype_for(kind: NoteKind, is_fake: bool) -> type[PlayArchetype]:
    key = (kind, is_fake)
    if key not in _NOTE_ARCHETYPE_BY_KIND and is_fake:
        key = (kind, False)
    return _NOTE_ARCHETYPE_BY_KIND[key]


def build_level(
    name: str,
    title: str,
    bgm: Asset | None,
    entities: list[LevelEntities],
) -> Level:
    bpm_changes: list[LevelBpmChange] = []
    level_ts_groups: list[LevelTimescaleGroup] = []
    level_stages: list[LevelStage] = []
    level_zoom_changes: list[LevelZoomChange] = []
    top_notes: list[LevelNote] = []
    slides: list[LevelSlide] = []

    for entity in entities:
        if isinstance(entity, LevelBpmChange):
            bpm_changes.append(entity)
        elif isinstance(entity, LevelTimescaleGroup):
            level_ts_groups.append(entity)
        elif isinstance(entity, LevelStage):
            level_stages.append(entity)
        elif isinstance(entity, LevelZoomChange):
            level_zoom_changes.append(entity)
        elif isinstance(entity, LevelNote):
            top_notes.append(entity)
        elif isinstance(entity, LevelSlide):
            slides.append(entity)
        else:
            raise TypeError(f"Unsupported level entity: {type(entity).__name__}")

    out_entities: list[PlayArchetype] = []

    default_ts_group: TimescaleGroup | None = None
    ts_group_map: dict[int, TimescaleGroup] = {}
    for level_group in level_ts_groups:
        group, group_entities = _build_timescale_group(level_group)
        ts_group_map[id(level_group)] = group
        out_entities.extend(group_entities)

    def resolve_ts_group(level_group: LevelTimescaleGroup | None) -> TimescaleGroup:
        nonlocal default_ts_group
        if level_group is not None:
            return ts_group_map[id(level_group)]
        if default_ts_group is None:
            default_level_group = LevelTimescaleGroup(changes=[LevelTimescaleChange(beat=0.0, timescale=1.0)])
            default_ts_group, group_entities = _build_timescale_group(default_level_group)
            out_entities.extend(group_entities)
        return default_ts_group

    stage_map: dict[int, DynamicStage] = {}
    for level_stage in level_stages:
        stage, stage_entities = _build_stage(level_stage)
        stage_map[id(level_stage)] = stage
        out_entities.extend(stage_entities)

    first_zoom = _build_zoom_changes(level_zoom_changes, out_entities)

    note_entities: list[PlayArchetype] = []
    slide_head_tail: dict[int, tuple[PlayArchetype, PlayArchetype]] = {}

    def emit_note(level_note: LevelNote, force_separator: bool = False) -> PlayArchetype:
        ts_group = resolve_ts_group(level_note.timescale_group)
        archetype_cls = _note_archetype_for(level_note.kind, level_note.is_fake)
        kwargs: dict[str, object] = {
            "beat": level_note.beat,
            "lane": level_note.lane,
            "size": level_note.size,
            "direction": level_note.direction,
            "connector_ease": level_note.connector_ease,
            "is_separator": level_note.is_separator or force_separator,
            "segment_kind": level_note.segment_kind,
            "segment_alpha": level_note.segment_alpha,
            "segment_layer": level_note.segment_layer,
            "timescale_group": ts_group.ref(),
        }
        if level_note.stage is not None:
            kwargs["stage_ref"] = stage_map[id(level_note.stage)].ref()
        note = archetype_cls(**kwargs)
        note_entities.append(note)
        out_entities.append(note)
        return note

    for level_note in top_notes:
        emit_note(level_note)

    pending_attachments: list[tuple[PlayArchetype, LevelSlide]] = []
    notes_by_level: dict[int, PlayArchetype] = {}

    for slide in slides:
        if len(slide.notes) < 2:
            raise ValueError("LevelSlide must contain at least two notes")
        built: list[PlayArchetype] = []
        for i, ln in enumerate(slide.notes):
            is_endpoint = i == 0 or i == len(slide.notes) - 1
            note = emit_note(ln, force_separator=is_endpoint)
            built.append(note)
            notes_by_level[id(ln)] = note
            if ln.attach is not None:
                pending_attachments.append((note, ln.attach))

        head = built[0]
        tail = built[-1]
        slide_head_tail[id(slide)] = (head, tail)
        head.next_ref = tail.ref()

        separator_indices = [
            i for i, ln in enumerate(slide.notes) if i == 0 or i == len(slide.notes) - 1 or ln.is_separator
        ]
        for a, b in itertools.pairwise(separator_indices):
            seg_head = built[a]
            seg_tail = built[b]
            seg_kind = slide.notes[a].segment_kind
            connector = Connector(
                head_ref=head.ref(),
                tail_ref=tail.ref(),
                segment_head_ref=seg_head.ref(),
                segment_tail_ref=seg_tail.ref(),
            )
            if seg_kind in {
                ConnectorKind.ACTIVE_NORMAL,
                ConnectorKind.ACTIVE_CRITICAL,
                ConnectorKind.ACTIVE_FAKE_NORMAL,
                ConnectorKind.ACTIVE_FAKE_CRITICAL,
            }:
                connector.active_head_ref = seg_head.ref()
                connector.active_tail_ref = seg_tail.ref()
            out_entities.append(connector)

    for note, slide in pending_attachments:
        head, tail = slide_head_tail[id(slide)]
        note.attach_head_ref = head.ref()
        note.attach_tail_ref = tail.ref()
        note.is_attached = True

    out_entities.extend(BpmChange(beat=level_bpm.beat, bpm=level_bpm.bpm) for level_bpm in bpm_changes)

    _emit_sim_lines(note_entities, out_entities)

    initialization = Initialization(
        revision=EngineRevision.LATEST,
        initial_life=1000,
    )
    if first_zoom is not None:
        initialization.first_zoom_ref = first_zoom.ref()
    out_entities.insert(0, initialization)

    sorted_entities = sorted(
        out_entities,
        key=lambda e: (not isinstance(e, Initialization), getattr(e, "beat", -1.0)),
    )

    return Level(
        name=name,
        title=title,
        bgm=bgm,
        data=LevelData(
            bgm_offset=0.0,
            entities=sorted_entities,
        ),
    )


def _build_timescale_group(
    level_group: LevelTimescaleGroup,
) -> tuple[TimescaleGroup, list[PlayArchetype]]:
    if not level_group.changes:
        raise ValueError("LevelTimescaleGroup must have at least one change")
    group = TimescaleGroup()
    change_entities: list[TimescaleChange] = []
    for level_change in sorted(level_group.changes, key=lambda c: c.beat):
        change = TimescaleChange(
            beat=level_change.beat,
            timescale=level_change.timescale,
            timescale_skip=level_change.timescale_skip,
            timescale_group=group.ref(),
            timescale_ease=level_change.timescale_ease,
            hide_notes=level_change.hide_notes,
        )
        if change_entities:
            change_entities[-1].next_ref = change.ref()
        change_entities.append(change)
    group.first_ref = change_entities[0].ref()
    return group, [group, *change_entities]


def _build_stage(level_stage: LevelStage) -> tuple[DynamicStage, list[PlayArchetype]]:
    stage = DynamicStage(from_start=level_stage.from_start)
    extra: list[PlayArchetype] = [stage]

    mask_events = [
        StageMaskChange(
            stage_ref=stage.ref(),
            beat=m.beat,
            lane=m.lane,
            size=m.size,
            ease=m.ease,
        )
        for m in sorted(level_stage.mask_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(mask_events)
    if mask_events:
        stage.first_mask_change_ref = mask_events[0].ref()
    extra.extend(mask_events)

    pivot_events = [
        StagePivotChange(
            stage_ref=stage.ref(),
            beat=p.beat,
            lane=p.lane,
            division_size=p.division_size,
            division_parity=p.division_parity,
            y_offset=p.y_offset,
            ease=p.ease,
        )
        for p in sorted(level_stage.pivot_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(pivot_events)
    if pivot_events:
        stage.first_pivot_change_ref = pivot_events[0].ref()
    extra.extend(pivot_events)

    style_events = [
        StageStyleChange(
            stage_ref=stage.ref(),
            beat=s.beat,
            judge_line_color=s.judge_line_color,
            left_border_style=s.left_border_style,
            right_border_style=s.right_border_style,
            alpha=s.alpha,
            lane_alpha=s.lane_alpha,
            ease=s.ease,
        )
        for s in sorted(level_stage.style_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(style_events)
    if style_events:
        stage.first_style_change_ref = style_events[0].ref()
    extra.extend(style_events)

    return stage, extra


def _build_zoom_changes(level_zooms: list[LevelZoomChange], out_entities: list[PlayArchetype]) -> ZoomChange | None:
    if not level_zooms:
        return None
    zoom_entities = [
        ZoomChange(beat=z.beat, zoom=z.zoom, ease=z.ease) for z in sorted(level_zooms, key=lambda z: z.beat)
    ]
    _chain_next_refs(zoom_entities)
    out_entities.extend(zoom_entities)
    return zoom_entities[0]


def _chain_next_refs(events: list) -> None:
    for i in range(len(events) - 1):
        events[i].next_ref = events[i + 1].ref()


def _emit_sim_lines(note_entities: list[PlayArchetype], out_entities: list[PlayArchetype]) -> None:
    buckets: dict[float, list[PlayArchetype]] = {}
    for note in note_entities:
        if note.key in _SIM_LINE_EXCLUDED_KINDS:
            continue
        buckets.setdefault(note.beat, []).append(note)
    for group in buckets.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda n: n.lane)
        for left, right in itertools.pairwise(group):
            out_entities.append(SimLine(left_ref=left.ref(), right_ref=right.ref()))
