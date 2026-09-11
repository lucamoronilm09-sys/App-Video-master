"""Schemi Pydantic: Project State + request/response models."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class VisionAnalysis(BaseModel):
    ai_used: bool = False
    vision_provider: Optional[str] = None
    vision_error: Optional[str] = None
    importance: float = 0.5
    story_value: float = 0.5
    emotional_intensity: float = 0.5
    subject_clarity: float = 0.5
    visual_interest: float = 0.5
    visual_quality: float = 0.5
    composition_balance: float = 0.5
    attention_score: float = 0.5
    people_count: int = 0
    faces_clear: float = 0.5
    is_group_photo: bool = False
    is_portrait: bool = False
    is_landscape: bool = False
    is_action: bool = False
    is_closeup: bool = False
    scene_type: str = "unknown"
    attention_center: str = "unknown"
    recommended_focus: str = "scene"
    recommended_pacing: str = "normal"
    repetition_risk: float = 0.25


class MediaItem(BaseModel):
    id: str
    source: Literal["local", "google_drive"]
    drive_file_id: Optional[str] = None
    path: str
    type: Literal["photo", "video"]
    orientation: Literal["landscape", "portrait", "square"]
    width: int
    height: int
    duration_sec: Optional[float] = None  # Per le foto: None fino a Edit Director; per i video: durata sorgente
    order_index: int
    fit_mode: Optional[Literal["cover", "contain"]] = None
    background_fill: Optional[Literal["blur", "solid_color"]] = None
    trim_start_sec: Optional[float] = None
    trim_end_sec: Optional[float] = None
    source_fps: Optional[float] = None
    face_count: int = 0
    composition_score: float = 0.5
    detail_score: float = 0.5
    sharpness_score: float = 0.5
    contrast_score: float = 0.5
    color_score: float = 0.5
    people_count: int = 0
    importance_score: float = 0.5
    vision_ai_used: bool = False
    scene_type: Optional[str] = None
    duration_source: str = "unknown"
    provisional_duration_sec: Optional[float] = None  # Solo per foto: durata UI prima dell'audio
    ai_duration_sec: Optional[float] = None  # Durata scelta dall'Edit Director
    ai_edit_score: Optional[float] = None
    music_sync: bool = False
    vision_analysis: Optional[VisionAnalysis] = None


class OutputSpec(BaseModel):
    resolution: str = "1920x1080"
    fps: int = 30
    background_fill: Literal["blur", "solid_color"] = "blur"
    vcodec: Literal["h264", "h265"] = "h264"


class AudioBlock(BaseModel):
    path: Optional[str] = None
    duration_sec: float = 0.0
    bpm: float = 0.0
    beat_times_sec: list[float] = Field(default_factory=list)
    downbeat_times_sec: list[float] = Field(default_factory=list)
    beat_markers_sec: list[float] = Field(default_factory=list)
    energy_curve: list[float] = Field(default_factory=list)


class AudioTrack(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    duration_sec: float = 0.0
    bpm: float = 0.0
    beat_times_sec: list[float] = Field(default_factory=list)
    downbeat_times_sec: list[float] = Field(default_factory=list)
    beat_markers_sec: list[float] = Field(default_factory=list)
    energy_curve: list[float] = Field(default_factory=list)


class ProjectState(BaseModel):
    schema_version: int
    project_id: str
    name: str = "Nuovo progetto"
    user_prompt: str = ""
    media: list[MediaItem] = Field(default_factory=list)
    audio: AudioBlock = Field(default_factory=AudioBlock)
    audio_tracks: list[AudioTrack] = Field(default_factory=list)
    style_profile: str = "album_memory"
    output_spec: OutputSpec = Field(default_factory=OutputSpec)
    edit_decision_list: list[dict[str, Any]] = Field(default_factory=list)
    story_chapters: list[dict[str, Any]] = Field(default_factory=list)
    music_structure: dict[str, Any] = Field(default_factory=dict)
    clip_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ai_feedback: Optional[dict[str, Any]] = None
    ai_feedback_history: list[dict[str, Any]] = Field(default_factory=list)
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


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    user_prompt: Optional[str] = Field(default=None, max_length=2000)
    style_profile: Optional[str] = Field(default=None, max_length=60)


class ProjectFeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    reasons: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=1000)


class DriveCredentialsRequest(BaseModel):
    client_id: str
    client_secret: str


class DriveImportRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    folder_ids: list[str] = Field(default_factory=list)


class ClipOverrideRequest(BaseModel):
    duration_sec: Optional[float] = None
    transition_out: Optional[float] = None
    ken_burns_movement: Optional[str] = None
