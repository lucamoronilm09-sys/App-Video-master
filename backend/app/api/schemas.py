"""Schemi Pydantic: Project State come definito dall'architettura (sez. 4),
piu' campi operativi (errors/pipeline_log) e modelli di request/response."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class MediaItem(BaseModel):
    id: str
    source: Literal["local", "google_drive"]
    drive_file_id: Optional[str] = None
    path: str
    type: Literal["photo", "video"]
    orientation: Literal["landscape", "portrait", "square"]
    width: int
    height: int
    duration_sec: float
    order_index: int
    fit_mode: Optional[Literal["cover", "contain"]] = None
    background_fill: Optional[Literal["blur", "solid_color"]] = None
    # M3 (Sequence Agent): trim centrale per video > 8s; None = nessun trim.
    trim_start_sec: Optional[float] = None
    trim_end_sec: Optional[float] = None
    # fps nativo rilevato all'import (solo video; None per foto/non rilevabile).
    # La UI lo usa per consigliare un fps di output senza conversioni a scatti.
    source_fps: Optional[float] = None


class OutputSpec(BaseModel):
    resolution: str = "1920x1080"
    fps: int = 30
    background_fill: Literal["blur", "solid_color"] = "blur"
    vcodec: Literal["h264", "h265"] = "h264"


class AudioBlock(BaseModel):
    path: Optional[str] = None
    duration_sec: float = 0.0
    bpm: float = 0.0
    beat_markers_sec: list[float] = Field(default_factory=list)
    energy_curve: list[float] = Field(default_factory=list)


class ProjectState(BaseModel):
    schema_version: int
    project_id: str
    media: list[MediaItem] = Field(default_factory=list)
    audio: AudioBlock = Field(default_factory=AudioBlock)
    style_profile: str = "album_memory"
    output_spec: OutputSpec = Field(default_factory=OutputSpec)
    edit_decision_list: list[dict[str, Any]] = Field(default_factory=list)
    clip_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    render_manifest: Optional[dict[str, Any]] = None
    qa_report: Optional[dict[str, Any]] = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_log: list[dict[str, Any]] = Field(default_factory=list)
    created_at: float
    updated_at: float


class HealthCheck(BaseModel):
    status: str
    service: str
    projects_count: int


class ReorderRequest(BaseModel):
    media_ids: list[str]


class UpdateMediaRequest(BaseModel):
    background_fill: Optional[Literal["blur", "solid_color"]] = None


class UpdateSettingsRequest(BaseModel):
    background_fill: Optional[Literal["blur", "solid_color"]] = None
    resolution: Optional[str] = None
    fps: Optional[int] = None
    vcodec: Optional[Literal["h264", "h265"]] = None


class DriveCredentialsRequest(BaseModel):
    client_id: str
    client_secret: str


class DriveImportRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    folder_ids: list[str] = Field(default_factory=list)


class ClipOverrideRequest(BaseModel):
    """Modifica manuale di una clip del montaggio (ogni campo è opzionale).

    - duration_sec: foto 1.0–12.0s; video 0.5s–durata sorgente (ricentra il trim).
    - transition_out: dissolvenza verso la clip successiva 0.0 (stacco)–1.5s.
    - ken_burns_movement: movimento foto (pan_left/pan_right/zoom_in_slow/
      zoom_out_slow/pan_and_zoom_diag/static) o "auto" per togliere l'override.
    """

    duration_sec: Optional[float] = None
    transition_out: Optional[float] = None
    ken_burns_movement: Optional[str] = None
