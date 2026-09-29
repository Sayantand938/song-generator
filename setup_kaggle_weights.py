"""
YuE2 Weights → Kaggle (all-in-one)

  1. Downloads YuE2 GGUF weights + sidecars from Hugging Face (skips existing)
  2. Authenticates via kagglehub.login() (interactive on first run, cached after)
  3. Uploads them to Kaggle as a private dataset

Requirements:
  pip install requests kagglehub python-dotenv rich

Usage:
  python setup_kaggle_weights.py
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

# ---------------- Config ----------------
HF_REPO_ID   = "audio-cpp/Yue2-3B-GGUF"
KAGGLE_SLUG  = "yue2-weights"
KAGGLE_TITLE = "YuE2 Weights"
BUILD_DIR    = Path("./yue2-weights-build")

FILES = [
    "yue2-3b-q8_0.gguf",
    "yue2-vae-f16.gguf",
    "sidecars/yue2-generation-config.json",
    "sidecars/yue2-model-config.json",
    "sidecars/yue2-qwen.tiktoken",
    "sidecars/yue2-vae-config.json",
]
# ----------------------------------------

console = Console()


def banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]YuE2 Weights → Kaggle[/bold cyan]\n"
        "[dim]Download from Hugging Face, upload to Kaggle as a private dataset[/dim]",
        border_style="cyan",
        padding=(1, 2),
    ))


def section(title: str) -> None:
    console.rule(f"[bold]{title}", style="dim")


# ================================================================
# Preflight
# ================================================================

def load_env() -> None:
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
        console.print(f"  [green]✓[/green] Loaded .env from [dim]{env_path.resolve()}[/dim]")
    else:
        console.print("  [yellow]⚠[/yellow] No .env found — relying on process env")


def resolve_kaggle_username() -> str:
    """Read username from .env, or from cached kagglehub login, or from legacy file."""
    user = os.getenv("KAGGLE_USERNAME")
    if user:
        console.print(f"  [green]✓[/green] Kaggle user: [bold]{user}[/bold] [dim](from .env)[/dim]")
        return user

    # Fall back to legacy kaggle.json
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.exists():
        try:
            import json
            data = json.loads(kaggle_json.read_text())
            console.print(f"  [green]✓[/green] Kaggle user: [bold]{data['username']}[/bold] "
                          f"[dim](from kaggle.json)[/dim]")
            return data["username"]
        except Exception:
            pass

    console.print(Panel(
        "[bold red]No Kaggle username found[/bold red]\n\n"
        "Add to your [cyan].env[/cyan]:\n\n"
        "  [white]KAGGLE_USERNAME=your_username[/white]",
        border_style="red",
    ))
    sys.exit(1)


def check_kagglehub() -> None:
    try:
        import kagglehub  # noqa: F401
        from importlib.metadata import version as pkg_version
        console.print(f"  [green]✓[/green] kagglehub {pkg_version('kagglehub')}")
    except ImportError:
        console.print("[red]✗ kagglehub not installed[/red]")
        console.print("  Run: [cyan]pip install kagglehub[/cyan]")
        sys.exit(1)


# ================================================================
# Download
# ================================================================

def _hf_url(filename: str) -> str:
    return f"https://huggingface.co/{HF_REPO_ID}/resolve/main/{filename}"


def _stream_download(url: str, dst: Path, hf_token: str | None,
                     progress: Progress, task_id) -> None:
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
    with requests.get(url, headers=headers, stream=True, allow_redirects=True,
                      timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0)) or None
        progress.update(task_id, total=total)
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    progress.update(task_id, advance=len(chunk))


def download_weights() -> None:
    section("Downloading weights")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "sidecars").mkdir(exist_ok=True)

    hf_token = os.getenv("HF_TOKEN")

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold white]{task.description}"),
        BarColumn(bar_width=30, complete_style="green", finished_style="green"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    ) as progress:
        for rel in FILES:
            filename = os.path.basename(rel)
            target_dir = BUILD_DIR / "sidecars" if rel.startswith("sidecars/") else BUILD_DIR
            dst = target_dir / filename

            if dst.exists() and dst.stat().st_size > 0:
                console.print(
                    f"  [green]✓[/green] {filename} "
                    f"[dim](already present · {dst.stat().st_size / 1e6:.1f} MB)[/dim]"
                )
                continue

            task_id = progress.add_task(filename, total=None)

            urls = [_hf_url(rel)]
            if rel != filename:
                urls.append(_hf_url(filename))

            last_err = None
            success = False
            for url in urls:
                try:
                    _stream_download(url, dst, hf_token, progress, task_id)
                    success = True
                    break
                except Exception as e:
                    last_err = e

            if not success:
                console.print(f"  [red]✗ Failed:[/red] {filename} — {last_err}")
                sys.exit(1)

            progress.update(task_id, description=f"[green]✓[/green] {filename}")


# ================================================================
# Auth (kagglehub.login handles interactive + caching)
# ================================================================

def authenticate() -> None:
    section("Authenticating with Kaggle")

    import kagglehub

    # kagglehub.login() will:
    #   - use cached credentials if present
    #   - otherwise prompt for a KGAT_ token interactively
    #   - validate + cache the token in ~/.cache/kagglehub/
    try:
        kagglehub.login()
        console.print("  [green]✓[/green] Kaggle credentials validated")
    except Exception as e:
        console.print(f"  [red]✗ Authentication failed:[/red] {e}")
        console.print("  [dim]Get a token at https://www.kaggle.com/settings/api[/dim]")
        sys.exit(1)


# ================================================================
# Upload
# ================================================================

def summarise_build() -> float:
    files = [f for f in BUILD_DIR.rglob("*") if f.is_file()]
    total_mb = sum(f.stat().st_size for f in files) / 1e6

    t = Table(box=box.ROUNDED, show_header=False, border_style="dim")
    t.add_column(style="bold cyan", no_wrap=True)
    t.add_column()
    t.add_row("Folder", str(BUILD_DIR.resolve()))
    t.add_row("Files", str(len(files)))
    t.add_row("Total", f"{total_mb:.0f} MB")
    console.print(t)
    return total_mb


def upload_via_kagglehub(username: str, total_mb: float) -> None:
    section("Pushing to Kaggle")

    import kagglehub

    handle = f"{username}/{KAGGLE_SLUG}"
    console.print(f"  Handle:   [bold]{handle}[/bold]")
    console.print(f"  Size:     [bold cyan]{total_mb:.0f} MB[/bold cyan]")
    console.print("  [dim]This can take several minutes — grab a coffee ☕[/dim]\n")

    try:
        result = kagglehub.dataset_upload(
            handle=handle,
            local_dataset_dir=str(BUILD_DIR),
            version_notes="Initial YuE2 weights",
        )
        console.print(f"\n  [green]✓[/green] Upload complete")
        if result:
            console.print(f"  [dim]Result: {result}[/dim]")
    except Exception as e:
        console.print(f"\n  [red]✗ Upload failed:[/red] {e}")
        raise


# ================================================================
# Summary
# ================================================================

def final_summary(username: str) -> None:
    console.print()
    table = Table(
        title="[bold green]Done![/bold green]",
        box=box.ROUNDED,
        show_header=False,
        border_style="green",
        padding=(0, 2),
    )
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()

    table.add_row("Dataset",   f"[white]{username}/{KAGGLE_SLUG}[/white]")
    table.add_row("Built at",  f"[dim]{BUILD_DIR.resolve()}[/dim]")
    table.add_row("", "")
    table.add_row("Next",      "[white]1.[/white] Open your Kaggle notebook")
    table.add_row("",          "[white]2.[/white] Right sidebar → Add Input → "
                               "search [cyan]yue2-weights[/cyan]")
    table.add_row("",          "[white]3.[/white] Re-run Cell 2 — expect:")
    table.add_row("",          "    [dim]⚡ Found pre-mounted weights — skipping download.[/dim]")
    table.add_row("", "")
    table.add_row("Cleanup",   f"[dim]Delete {BUILD_DIR.name}/ after verifying[/dim]")

    console.print(table)
    console.print()


# ================================================================
# Main
# ================================================================

def main() -> None:
    banner()

    section("Preflight")
    load_env()
    check_kagglehub()
    username = resolve_kaggle_username()

    download_weights()

    section("Build summary")
    total_mb = summarise_build()

    authenticate()
    upload_via_kagglehub(username, total_mb)
    final_summary(username)


if __name__ == "__main__":
    main()