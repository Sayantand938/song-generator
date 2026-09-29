from typing import Optional
import typer
from src.config import DEFAULT_MODEL
from src.core.lyricist import run_lyricist
from src.core.local_runner import run_local_batch
from src.core.hf_vault import (
    dispatch_queue, collect_songs, clean_vault, retry_failed,
)
from src.core.video_maker import run_video_maker
from src.core.uploader import run_youtube_uploader
from src.core.status import run_status

app = typer.Typer(
    name="song-generator",
    help="Autonomous AI Music Studio (YuE2 & Suno Batch Pipeline)",
    add_completion=False,
)


@app.command("write")
def write_command(
    count: int = typer.Option(3, "--count", "-n", "-c", help="Number of songs to generate", min=1, max=50),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Optional theme or musical style"),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Model ID to use for generation"),
):
    """Pass 1 & Pass 2: Brainstorm concepts and write full lyrics."""
    run_lyricist(count=count, theme=theme, model=model)


@app.command("local")
def local_command(
    seed: Optional[int] = typer.Option(None, "--seed", help="Base seed (applied as seed+i per song) for reproducible generation"),
):
    """Render songs locally using AMD RX 7800 XT (Vulkan / audio.cpp)."""
    run_local_batch(seed=seed)


@app.command("dispatch")
def dispatch_command(
    seed: Optional[int] = typer.Option(None, "--seed", help="Base seed (applied as seed+i per song)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be queued without uploading"),
):
    """Upload pending songs to Hugging Face queue for Kaggle workers."""
    dispatch_queue(seed=seed, dry_run=dry_run)


@app.command("collect")
def collect_command():
    """Download ZIP bundles from Hugging Face and extract into songs/<slug>/."""
    collect_songs()


@app.command("retry")
def retry_command(
    song: Optional[str] = typer.Option(None, "--song", "-s", help="Retry only this song slug"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be retried without uploading"),
):
    """Re-mark failed jobs on the HF queue as pending."""
    retry_failed(song_slug=song, dry_run=dry_run)


@app.command("status")
def status_command(
    song: Optional[str] = typer.Option(None, "--song", "-s", help="Show only this song slug"),
    remote: bool = typer.Option(False, "--remote", "-r", help="Also fetch remote job status from HF"),
):
    """Show local + remote status of every song in the library."""
    run_status(song_slug=song, remote=remote)


@app.command("video")
def video_command(
    song: Optional[str] = typer.Option(None, "--song", "-s", help="Specific song slug to render (defaults to all)"),
    keep_wav: bool = typer.Option(False, "--keep-wav", help="Retain master .wav file after video creation"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-rendering even if video already exists"),
):
    """Generate 1080p YouTube MP4 videos with custom typography thumbnails."""
    run_video_maker(song_slug=song, keep_wav=keep_wav, force=force)


@app.command("upload")
def upload_command(
    song: Optional[str] = typer.Option(None, "--song", "-s", help="Specific song slug (defaults to all ready videos)"),
    privacy: str = typer.Option("public", "--privacy", "-p", help="YouTube privacy (unlisted, private, public)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-upload even if receipt exists"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be uploaded without uploading"),
):
    """Upload rendered videos to YouTube with Title-Case metadata and thumbnails."""
    run_youtube_uploader(song_slug=song, privacy_status=privacy, force=force, dry_run=dry_run)


@app.command("clean")
def clean_command():
    """Reset Hugging Face queue and delete remote outputs."""
    clean_vault()