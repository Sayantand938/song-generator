import json
import re
import time
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any

from src.config import AUDIO_EXTENSIONS, SYSTEM_PROMPT_PATH, MANIFESTS_DIR


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or f"track-{int(time.time())}"


# ---------- Info.md section parsing ----------

def parse_info_md(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Extract Style and Lyrics sections from an info.md file (ignores Meta/Score)."""
    try:
        content = file_path.read_text(encoding="utf-8")
        style_match = re.search(
            r"^#\s*Style\s*\n(.*?)(?=^#\s|\Z)",
            content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
        )
        lyrics_match = re.search(
            r"^#\s*Lyrics\s*\n(.*?)(?=^#\s|\Z)",
            content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
        )
        if not style_match or not lyrics_match:
            return None, None
        return style_match.group(1).strip(), lyrics_match.group(1).strip()
    except Exception as e:
        log(f"⚠️ Error reading {file_path.name}: {e}")
        return None, None


def parse_meta(file_path: Path) -> Dict[str, str]:
    """Extract the Meta section as a dict of key: value pairs (empty if absent)."""
    try:
        content = file_path.read_text(encoding="utf-8")
        m = re.search(
            r"^#\s*Meta\s*\n(.*?)(?=^#\s|\Z)",
            content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
        )
        if not m:
            return {}
        meta: Dict[str, str] = {}
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
        return meta
    except Exception:
        return {}


def parse_score(file_path: Path) -> Optional[str]:
    """Extract the Score (ABC notation) block from info.md, or None."""
    try:
        content = file_path.read_text(encoding="utf-8")
        m = re.search(
            r"^#\s*Score\s*\n(.*?)(?=^#\s|\Z)",
            content, re.DOTALL | re.MULTILINE | re.IGNORECASE,
        )
        return m.group(1).strip() if m else None
    except Exception:
        return None


def append_score_and_meta(
    file_path: Path,
    abc: Optional[str],
    meta: Optional[Dict[str, Any]],
) -> None:
    """Append (or replace) Meta + Score sections at the end of info.md."""
    if not file_path.exists():
        log(f"⚠️ Cannot write score/meta — {file_path.name} not found.")
        return

    content = file_path.read_text(encoding="utf-8")

    # Strip any existing Meta / Score sections (idempotent re-merge)
    content = re.sub(
        r"^#\s*(?:Meta|Score)\s*\n.*?(?=^#\s|\Z)",
        "", content, flags=re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    content = content.rstrip() + "\n"

    new_sections = []
    if meta:
        lines = ["# Meta", ""]
        for k, v in meta.items():
            lines.append(f"{k}: {v}")
        new_sections.append("\n".join(lines))

    if abc:
        new_sections.append(f"# Score\n\n{abc.strip()}")

    if new_sections:
        content += "\n\n" + "\n\n".join(new_sections) + "\n"

    file_path.write_text(content, encoding="utf-8")


# ---------- Library helpers ----------

def has_audio_file(folder_path: Path) -> bool:
    if not folder_path.is_dir():
        return False
    return any(f.suffix.lower() in AUDIO_EXTENSIONS for f in folder_path.iterdir())


def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(f"System prompt file not found at: {SYSTEM_PROMPT_PATH}")
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


# ---------- Manifest helpers ----------

def new_batch_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def write_manifest(batch_id: str, mode: str, songs: List[Dict[str, Any]], **extras) -> Path:
    payload = {
        "batch_id": batch_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "songs": songs,
    }
    payload.update(extras)
    path = MANIFESTS_DIR / f"{batch_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def update_manifest(batch_id: str, songs: List[Dict[str, Any]]) -> Optional[Path]:
    path = MANIFESTS_DIR / f"{batch_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["songs"] = songs
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
    except Exception:
        return None