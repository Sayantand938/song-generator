import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import SONGS_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, ROOT_DIR

console = Console()

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image, ImageDraw, ImageFont = None, None, None

try:
    from titlecase import titlecase
except ImportError:
    def titlecase(text: str) -> str:
        return " ".join(word.capitalize() for word in text.split())


# ---------- Font resolution (JetBrains Mono preferred) ----------

_JETBRAINS_URL = (
    "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/"
    "v2.304/fonts/ttf/JetBrainsMono-Bold.ttf"
)
_LOCAL_FONT_DIR = ROOT_DIR / "fonts"
_LOCAL_FONT_PATH = _LOCAL_FONT_DIR / "JetBrainsMono-Bold.ttf"
_jetbrains_resolved = False  # cached after first check


SYSTEM_FONTS = [
    r"C:\Windows\Fonts\JetBrainsMono-Bold.ttf",
    r"C:\Windows\Fonts\JetBrainsMono-Regular.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _ensure_local_jetbrains() -> Optional[Path]:
    """Download JetBrains Mono Bold to ./fonts/ on first use. Returns path or None."""
    global _jetbrains_resolved
    if _LOCAL_FONT_PATH.exists() and _LOCAL_FONT_PATH.stat().st_size > 0:
        return _LOCAL_FONT_PATH
    if _jetbrains_resolved:
        return None
    _jetbrains_resolved = True

    try:
        import requests
        console.print("  [dim]↓ Fetching JetBrains Mono Bold for thumbnails…[/dim]")
        _LOCAL_FONT_DIR.mkdir(parents=True, exist_ok=True)
        r = requests.get(_JETBRAINS_URL, timeout=30)
        r.raise_for_status()
        _LOCAL_FONT_PATH.write_bytes(r.content)
        console.print(f"  [green]✓[/green] Saved to [dim]{_LOCAL_FONT_PATH.relative_to(ROOT_DIR)}[/dim]")
        return _LOCAL_FONT_PATH
    except Exception as e:
        console.print(f"  [yellow]⚠️ Could not fetch JetBrains Mono: {e}[/yellow]")
        return None


def _get_font(size: int):
    # Prefer local JetBrains Mono (auto-downloaded)
    local = _ensure_local_jetbrains()
    if local and local.exists():
        try:
            return ImageFont.truetype(str(local), size)
        except Exception:
            pass

    # Fall back to system fonts
    for candidate in SYSTEM_FONTS:
        p = Path(candidate)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue

    return ImageFont.load_default()


# ---------- Text helpers ----------

def to_title_case(text: str) -> str:
    clean = re.sub(r"[\-_]+", " ", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return text
    return titlecase(clean)


def get_fitted_title_layout(title, draw, max_w=1520, max_h=600):
    words = title.split()
    for font_size in range(88, 38, -4):
        font = _get_font(font_size)
        lines, cur_line, overflow = [], [], False
        for word in words:
            test_line = " ".join(cur_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_w:
                cur_line.append(word)
            else:
                if not cur_line:
                    overflow = True
                    break
                lines.append(" ".join(cur_line))
                cur_line = [word]
                bw = draw.textbbox((0, 0), word, font=font)
                if bw[2] - bw[0] > max_w:
                    overflow = True
                    break
        if cur_line:
            lines.append(" ".join(cur_line))
        if overflow or len(lines) > 3:
            continue
        spacing = int(font_size * 0.35)
        bboxes = [draw.textbbox((0, 0), l, font=font) for l in lines]
        heights = [b[3] - b[1] for b in bboxes]
        if sum(heights) + (len(lines) - 1) * spacing <= max_h:
            return lines, font, bboxes, heights, spacing
    fallback = _get_font(40)
    bbox = draw.textbbox((0, 0), title, font=fallback)
    return [title], fallback, [bbox], [bbox[3] - bbox[1]], 14


# ---------- Thumbnail ----------

def create_thumbnail(song_dir: Path, slug: str) -> Path:
    if Image is None:
        raise RuntimeError("Pillow is not installed. Run: pip install pillow")
    thumbnail_file = song_dir / f"{slug}-thumbnail.png"
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    display_title = to_title_case(slug)
    lines, font, bboxes, heights, spacing = get_fitted_title_layout(
        display_title, draw, max_w=VIDEO_WIDTH - 400, max_h=VIDEO_HEIGHT - 350,
    )
    total_h = sum(heights) + (len(lines) - 1) * spacing
    cur_y = (VIDEO_HEIGHT - total_h) // 2
    for i, line in enumerate(lines):
        line_w = bboxes[i][2] - bboxes[i][0]
        draw.text(((VIDEO_WIDTH - line_w) // 2, cur_y), line, font=font, fill=(255, 255, 255))
        cur_y += heights[i] + spacing
    img.save(thumbnail_file, "PNG", optimize=True)
    return thumbnail_file


# ---------- Video encode ----------

def create_video(song_dir: Path, slug: str, audio_source: Path, thumbnail_file: Path) -> bool:
    video_file = song_dir / f"{slug}.mp4"
    temp_video_file = song_dir / f"{slug}-temp.mp4"

    qsv = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30",
           "-i", str(thumbnail_file), "-i", str(audio_source),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23",
           "-c:a", "aac", "-b:a", "320k", "-pix_fmt", "nv12",
           "-shortest", "-movflags", "+faststart", str(temp_video_file)]
    cpu = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30",
           "-i", str(thumbnail_file), "-i", str(audio_source),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "320k", "-pix_fmt", "yuv420p",
           "-shortest", "-movflags", "+faststart", str(temp_video_file)]

    console.print("  [cyan]• Encoding with Intel Quick Sync (QSV)...[/cyan]")
    result = subprocess.run(qsv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        console.print("  [yellow]• QSV unavailable. Falling back to CPU libx264...[/yellow]")
        result = subprocess.run(cpu, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode != 0 or not temp_video_file.exists() or temp_video_file.stat().st_size == 0:
        console.print(f"  [red]❌ Video encoding failed for '{slug}'.[/red]")
        if temp_video_file.exists():
            temp_video_file.unlink(missing_ok=True)
        return False
    shutil.move(str(temp_video_file), str(video_file))
    return True


# ---------- Orchestration ----------

def process_song_video(song_dir: Path, keep_wav: bool = False, force: bool = False) -> str:
    slug = song_dir.name
    audio_file = song_dir / f"{slug}.wav"
    if not audio_file.exists():
        candidates = list(song_dir.glob("*.wav"))
        if candidates:
            audio_file = candidates[0]

    video_file = song_dir / f"{slug}.mp4"
    if not audio_file.exists():
        return "skip_no_audio"
    if video_file.exists() and video_file.stat().st_size > 0 and not force:
        return "already_exists"

    console.print(f"\n[bold white]🎬 Processing:[/] [cyan]{slug}[/cyan]")
    console.print(f"  [dim]Title Card:[/] \"[bold white]{to_title_case(slug)}[/bold white]\"")

    try:
        thumb = create_thumbnail(song_dir, slug)
        console.print(f"  [green]✓ Thumbnail:[/] [dim]{thumb.name}[/dim]")
    except Exception as e:
        console.print(f"  [red]❌ Thumbnail error:[/] {e}")
        return "failed"

    if not create_video(song_dir, slug, audio_file, thumb):
        return "failed"

    console.print(f"  [green]✓ Video:[/] [bold cyan]{video_file.name}[/bold cyan]")

    if not keep_wav:
        try:
            audio_file.unlink()
            console.print(f"  [dim]🗑️ Deleted {audio_file.name}[/dim]")
        except Exception as e:
            console.print(f"  [yellow]⚠️ Could not delete WAV:[/] {e}")
            return "completed_kept_wav"
    return "completed"


def run_video_maker(song_slug: Optional[str] = None, keep_wav: bool = False, force: bool = False) -> None:
    console.print(Panel.fit(
        "[bold cyan]Video Studio[/bold cyan]\n[dim]Pitch Black with JetBrains Mono Typography[/dim]",
        border_style="blue",
    ))
    if Image is None:
        console.print("[bold red]❌ Pillow is not installed.[/bold red]"); raise SystemExit(1)
    if shutil.which("ffmpeg") is None:
        console.print("[bold red]❌ FFmpeg not found in PATH.[/bold red]"); raise SystemExit(1)

    if song_slug:
        target = SONGS_DIR / song_slug
        if not target.is_dir():
            console.print(f"[bold red]❌ Folder not found:[/] {target}"); return
        targets = [target]
    else:
        targets = sorted(p for p in SONGS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))

    if not targets:
        console.print("[yellow]⚠️ No song folders.[/yellow]"); return

    counts = {"completed": 0, "already_exists": 0, "skip_no_audio": 0, "failed": 0, "completed_kept_wav": 0}
    for folder in targets:
        r = process_song_video(folder, keep_wav=keep_wav, force=force)
        counts[r] = counts.get(r, 0) + 1

    t = Table(title="🎬 Video Generation Summary", box=box.ROUNDED, header_style="bold magenta")
    t.add_column("Status", style="bold")
    t.add_column("Count", justify="center")
    t.add_row("[green]Created[/green]", str(counts["completed"] + counts["completed_kept_wav"]))
    t.add_row("[cyan]Already Existed[/cyan]", str(counts["already_exists"]))
    t.add_row("[dim]No Audio[/dim]", str(counts["skip_no_audio"]))
    t.add_row("[red]Failed[/red]", str(counts["failed"]))
    console.print("\n"); console.print(t)