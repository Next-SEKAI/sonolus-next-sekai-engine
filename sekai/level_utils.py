from __future__ import annotations

import itertools
import struct
from dataclasses import dataclass, field
from typing import cast

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
    CameraChange,
    DynamicStage,
    StageMaskChange,
    StagePivotChange,
    StageStyleChange,
)
from sekai.play.initialization import Initialization
from sekai.play.note import NOTE_ARCHETYPES, BaseNote
from sekai.play.sim_line import SimLine
from sekai.play.timescale import TimescaleChange, TimescaleGroup


def _build_note_archetype_lookup() -> dict[tuple[NoteKind, bool], type[PlayArchetype]]:
    lookup: dict[tuple[NoteKind, bool], type[PlayArchetype]] = {}
    for archetype in NOTE_ARCHETYPES:
        is_fake = str(archetype.name).startswith("Fake")
        lookup[(cast(NoteKind, archetype.key), is_fake)] = archetype
    return lookup


_NOTE_ARCHETYPE_BY_KIND = _build_note_archetype_lookup()

_SIM_LINE_EXCLUDED_KINDS = frozenset({NoteKind.ANCHOR, NoteKind.NORM_TICK, NoteKind.CRIT_TICK, NoteKind.HIDE_TICK})


def _build_silent_wav(duration_seconds: float = 60.0, sample_rate: int = 8000) -> bytes:
    num_samples = int(duration_seconds * sample_rate)
    data_size = num_samples  # 1 channel, 8-bit
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # channels
        sample_rate,
        sample_rate,  # byte rate = sample_rate * channels * bits/8
        1,  # block align
        8,  # bits per sample
        b"data",
        data_size,
    )
    return header + b"\x80" * data_size


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
    force_note_speed: float = 0.0


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
    abs_y_offset: float
    y_beat_offset: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStageStyleChange:
    beat: float
    judge_line_color: JudgeLineColor
    left_border_style: StageBorderStyle
    right_border_style: StageBorderStyle
    alpha: float
    lane_alpha: float
    judge_line_alpha: float
    ease: EaseType = EaseType.LINEAR


@dataclass
class LevelStage:
    from_start: bool = False
    until_end: bool = False
    mask_changes: list[LevelStageMaskChange] = field(default_factory=list)
    pivot_changes: list[LevelStagePivotChange] = field(default_factory=list)
    style_changes: list[LevelStageStyleChange] = field(default_factory=list)


@dataclass
class LevelCameraChange:
    beat: float
    lane: float = 0.0
    size: float = 6.0
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


type LevelEntities = LevelBpmChange | LevelTimescaleGroup | LevelNote | LevelSlide | LevelStage | LevelCameraChange


def _apply_ease(ease_type: EaseType, x: float) -> float:
    x = max(0.0, min(1.0, x))
    if ease_type == EaseType.NONE:
        return 0.0 if x < 1.0 else 1.0
    if ease_type == EaseType.LINEAR:
        return x
    if ease_type == EaseType.IN_QUAD:
        return x * x
    if ease_type == EaseType.OUT_QUAD:
        return 1.0 - (1.0 - x) * (1.0 - x)
    if ease_type == EaseType.IN_OUT_QUAD:
        return 2.0 * x * x if x < 0.5 else 1.0 - (-2.0 * x + 2.0) ** 2 / 2.0
    if ease_type == EaseType.OUT_IN_QUAD:
        return (1.0 - (1.0 - 2.0 * x) ** 2) / 2.0 if x < 0.5 else 0.5 + ((2.0 * x - 1.0) ** 2) / 2.0
    return x


def _pivot_lane_at(level_stage: LevelStage, beat: float) -> float:
    pivots = sorted(level_stage.pivot_changes, key=lambda p: p.beat)
    if not pivots:
        return 0.0
    pivot_a: LevelStagePivotChange | None = None
    pivot_b: LevelStagePivotChange | None = None
    for p in pivots:
        if p.beat <= beat:
            pivot_a = p
        else:
            pivot_b = p
            break
    if pivot_a is None:
        return pivots[0].lane
    if pivot_b is None or pivot_b.beat == pivot_a.beat:
        return pivot_a.lane
    frac = _apply_ease(pivot_a.ease, (beat - pivot_a.beat) / (pivot_b.beat - pivot_a.beat))
    return pivot_a.lane + (pivot_b.lane - pivot_a.lane) * frac


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
    level_camera_changes: list[LevelCameraChange] = []
    top_notes: list[LevelNote] = []
    slides: list[LevelSlide] = []

    for entity in entities:
        if isinstance(entity, LevelBpmChange):
            bpm_changes.append(entity)
        elif isinstance(entity, LevelTimescaleGroup):
            level_ts_groups.append(entity)
        elif isinstance(entity, LevelStage):
            level_stages.append(entity)
        elif isinstance(entity, LevelCameraChange):
            level_camera_changes.append(entity)
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

    first_camera = _build_camera_changes(level_camera_changes, out_entities)

    note_entities: list[BaseNote] = []
    slide_head_tail: dict[int, tuple[BaseNote, BaseNote]] = {}

    def emit_note(level_note: LevelNote, force_separator: bool = False) -> BaseNote:
        ts_group = resolve_ts_group(level_note.timescale_group)
        archetype_cls = _note_archetype_for(level_note.kind, level_note.is_fake)
        if level_note.stage is not None:
            pivot_lane = _pivot_lane_at(level_note.stage, level_note.beat)
            abs_lane = pivot_lane + level_note.lane
            rel_lane = level_note.lane
        else:
            abs_lane = level_note.lane
            rel_lane = 0.0
        kwargs: dict[str, object] = {
            "beat": level_note.beat,
            "lane": abs_lane,
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
            kwargs["rel_lane"] = rel_lane
        note = cast(BaseNote, archetype_cls(**kwargs))
        note_entities.append(note)
        out_entities.append(note)
        return note

    for level_note in top_notes:
        emit_note(level_note)

    pending_attachments: list[tuple[BaseNote, LevelSlide]] = []
    notes_by_level: dict[int, BaseNote] = {}

    for slide in slides:
        if len(slide.notes) < 2:
            raise ValueError("LevelSlide must contain at least two notes")
        built: list[BaseNote] = []
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
    if first_camera is not None:
        initialization.first_camera_ref = first_camera.ref()
    out_entities.insert(0, initialization)

    sorted_entities = sorted(
        out_entities,
        key=lambda e: (not isinstance(e, Initialization), getattr(e, "beat", -1.0)),
    )

    return Level(
        name=name,
        title=title,
        bgm=bgm if bgm is not None else _build_silent_wav(),
        data=LevelData(
            bgm_offset=0.0,
            entities=list(sorted_entities),
        ),
    )


def _build_timescale_group(
    level_group: LevelTimescaleGroup,
) -> tuple[TimescaleGroup, list[PlayArchetype]]:
    if not level_group.changes:
        raise ValueError("LevelTimescaleGroup must have at least one change")
    group = TimescaleGroup(force_note_speed=level_group.force_note_speed)
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
    stage = DynamicStage(from_start=level_stage.from_start, until_end=level_stage.until_end)
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
            abs_y_offset=p.abs_y_offset,
            y_beat_offset=p.y_beat_offset,
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
            judge_line_alpha=s.judge_line_alpha,
            ease=s.ease,
        )
        for s in sorted(level_stage.style_changes, key=lambda c: c.beat)
    ]
    _chain_next_refs(style_events)
    if style_events:
        stage.first_style_change_ref = style_events[0].ref()
    extra.extend(style_events)

    return stage, extra


def _build_camera_changes(
    level_cameras: list[LevelCameraChange], out_entities: list[PlayArchetype]
) -> CameraChange | None:
    if not level_cameras:
        return None
    camera_entities = [
        CameraChange(beat=c.beat, lane=c.lane, size=c.size, ease=c.ease)
        for c in sorted(level_cameras, key=lambda c: c.beat)
    ]
    _chain_next_refs(camera_entities)
    out_entities.extend(camera_entities)
    return camera_entities[0]


def _chain_next_refs(events: list) -> None:
    for i in range(len(events) - 1):
        events[i].next_ref = events[i + 1].ref()


def _emit_sim_lines(note_entities: list[BaseNote], out_entities: list[PlayArchetype]) -> None:
    buckets: dict[float, list[BaseNote]] = {}
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
