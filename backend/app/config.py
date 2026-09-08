"""Configurazione centralizzata del backend AI Video Maker."""
from pathlib import Path

# backend/app/config.py -> repo root = parent.parent.parent
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

DATA_DIR = REPO_ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
MEDIA_SUBDIR = "media"      # dentro la cartella di un progetto
AUDIO_SUBDIR = "audio"
OUTPUT_SUBDIR = "output"
THUMBS_SUBDIR = "thumbs"    # anteprime leggere (cache, M-polish)

# output_spec di default (vedi Project State nel documento di architettura)
DEFAULT_OUTPUT_SPEC: dict = {
    "resolution": "1920x1080",
    "fps": 30,
    "background_fill": "blur",
    "vcodec": "h264",
}
DEFAULT_STYLE_PROFILE = "album_memory"

# NOTA: TOOLS_DIR è stato rimosso in quanto non utilizzato.
# Gli agenti Render/Timeline invocano ffmpeg/ffprobe assumendo che siano nel PATH di sistema.
