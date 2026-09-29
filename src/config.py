import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------- Paths ----------
SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
SONGS_DIR = ROOT_DIR / "songs"
MANIFESTS_DIR = SONGS_DIR / ".manifests"

# ---------- System prompt ----------
_custom_prompt_env = os.getenv("SYSTEM_PROMPT_FILE")
if _custom_prompt_env and (ROOT_DIR / _custom_prompt_env).exists():
    SYSTEM_PROMPT_PATH = ROOT_DIR / _custom_prompt_env
elif (ROOT_DIR / "config" / "system-prompt.md").exists():
    SYSTEM_PROMPT_PATH = ROOT_DIR / "config" / "system-prompt.md"
else:
    SYSTEM_PROMPT_PATH = ROOT_DIR / "system-prompt.md"

# ---------- Media ----------
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".aac", ".ogg", ".m4a", ".mp4"}

# ---------- Hugging Face Vault (queue + outputs) ----------
# Both must be set in .env — no defaults, so a public repo never leaks a username.
HF_TOKEN = os.getenv("HF_TOKEN")
HF_REPO = os.getenv("HF_REPO", "")

# ---------- Local audio.cpp ----------
LOCAL_SERVER_URL = os.getenv("LOCAL_SERVER_URL", "http://127.0.0.1:8080")

# ---------- LLM ----------
AICREDITS_API_KEY = os.getenv("AICREDITS_API_KEY")
AICREDITS_BASE_URL = os.getenv("AICREDITS_BASE_URL", "https://api.aicredits.in/v1")
DEFAULT_MODEL = os.getenv("MODEL_NAME", "google/gemini-3.8-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.75))

# ---------- Video ----------
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FONT_SIZE = 110

# ---------- YouTube ----------
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE", str(ROOT_DIR / "client_secret.json")
)
YOUTUBE_TOKEN_FILE = os.getenv(
    "YOUTUBE_TOKEN_FILE", str(ROOT_DIR / "youtube_token.json")
)

# ---------- Generation defaults (shared w/ Kaggle) ----------
DEFAULT_GUIDANCE_SCALE = 1.02
DEFAULT_NUM_INFERENCE_STEPS = 32
DEFAULT_COT = "full"

# ---------- Lyric length sanity ----------
LYRICS_MAX_CHARS = 4000
LYRICS_MAX_LINES = 120

# ---------- Ensure dirs ----------
SONGS_DIR.mkdir(parents=True, exist_ok=True)
MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)