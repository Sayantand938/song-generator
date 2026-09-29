from typing import Optional
from rich import box
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.config import SONGS_DIR, HF_REPO
from src.core.hf_vault import _fetch_remote_jobs

console = Console()


def run_status(song_slug: Optional[str] = None, remote: bool = False) -> None:
    console.print(
        Panel.fit(
            f"[bold cyan]Song Library Status[/bold cyan]\n"
            f"[dim]Remote: {'enabled (' + HF_REPO + ')' if remote else 'disabled'}[/dim]",
            border_style="blue",
        )
    )

    if song_slug:
        target = SONGS_DIR / song_slug
        if not target.is_dir():
            console.print(f"[bold red]❌ Song folder not found:[/] {target}")
            return
        folders = [target]
    else:
        folders = sorted(p for p in SONGS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))

    if not folders:
        console.print("[yellow]⚠️ No song folders found.[/yellow]")
        return

    remote_status = {}
    if remote:
        with console.status("Fetching remote ledger from HF..."):
            jobs = _fetch_remote_jobs()
        remote_status = {j["job_id"]: j.get("status", "—") for j in jobs}

    table = Table(box=box.ROUNDED, header_style="bold magenta", title=f"📚 {len(folders)} Song(s)")
    table.add_column("Slug", style="bold white")
    table.add_column("Info", justify="center")
    table.add_column("WAV", justify="center")
    table.add_column("MP4", justify="center")
    table.add_column("PNG", justify="center")
    table.add_column("Receipt", justify="center")
    if remote:
        table.add_column("Remote", justify="center")

    def icon(yes: bool, style_yes: str = "green", style_no: str = "dim") -> str:
        return f"[{style_yes}]✓[/]" if yes else f"[{style_no}]·[/]"

    for folder in folders:
        slug = folder.name
        has_info = bool(next((f for f in folder.iterdir() if f.name.endswith("-info.md")), None))
        has_wav = (folder / f"{slug}.wav").exists()
        has_mp4 = (folder / f"{slug}.mp4").exists()
        has_png = (folder / f"{slug}-thumbnail.png").exists()
        has_receipt = (folder / f"{slug}-receipt.json").exists()

        row = [
            slug,
            icon(has_info, "cyan"),
            icon(has_wav, "green"),
            icon(has_mp4, "yellow"),
            icon(has_png, "magenta"),
            icon(has_receipt, "green"),
        ]
        if remote:
            r_stat = remote_status.get(slug, "—")
            style = {"completed": "green", "audio_generated": "yellow",
                     "pending": "cyan", "failed": "red"}.get(r_stat, "dim")
            row.append(f"[{style}]{r_stat}[/]")

        table.add_row(*row)

    console.print(table)