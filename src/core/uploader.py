import base64
import json
import re
import textwrap
import time
from pathlib import Path
from typing import Optional, Dict, Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from src.config import SONGS_DIR, YOUTUBE_CLIENT_SECRETS_FILE, YOUTUBE_TOKEN_FILE
from src.utils import parse_info_md, parse_meta, parse_score

console = Console()

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

try:
    from titlecase import titlecase
except ImportError:
    def titlecase(text: str) -> str:
        return " ".join(word.capitalize() for word in text.split())


def to_title_case(text: str) -> str:
    clean = re.sub(r"[\-_]+", " ", text).strip()
    clean = re.sub(r"\s+", " ", clean)
    return titlecase(clean) if clean else text


# ================================================================
# YouTube client
# ================================================================

def get_youtube_client():
    creds = None
    token_path = Path(YOUTUBE_TOKEN_FILE)
    secrets_path = Path(YOUTUBE_CLIENT_SECRETS_FILE)

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            console.print("  [cyan]🔄 Refreshing YouTube OAuth token...[/cyan]")
            creds.refresh(Request())
        else:
            if not secrets_path.exists():
                console.print(Panel(
                    f"[bold red]Missing OAuth Credentials File![/bold red]\n\n"
                    f"Expected at: [yellow]{secrets_path}[/yellow]\n\n"
                    "Setup:\n"
                    "1. Google Cloud Console → enable YouTube Data API v3\n"
                    "2. Create OAuth 2.0 Desktop client ID\n"
                    "3. Download JSON, rename to client_secret.json, drop in project root.",
                    border_style="red",
                ))
                raise SystemExit(1)
            console.print("  [yellow]🔑 Authorizing with YouTube (browser)...[/yellow]")
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        console.print("  [green]✓ Token saved.[/green]")

    return build("youtube", "v3", credentials=creds)


# ================================================================
# Metadata builder (description content)
# ================================================================

def build_metadata(song_dir: Path, slug: str) -> Dict[str, Any]:
    """
    Build YouTube metadata: Style + Lyrics + Meta (no Score — that goes in a comment).
    Enforces the 5000-BYTE API limit for descriptions.
    """
    display_title = to_title_case(slug)
    info_file = next((f for f in song_dir.glob("*-info.md")), None)

    style, lyrics, meta = None, None, {}
    if info_file and info_file.exists():
        style, lyrics = parse_info_md(info_file)
        meta = parse_meta(info_file)

    parts = []
    if style:
        parts.append(f"# Style\n\n{style}")
    if lyrics:
        parts.append(f"# Lyrics\n\n{lyrics}")
    if meta:
        # Keep only the useful fields for viewers — order matters
        keep = ("seed", "model", "model_gguf", "vae_gguf",
                "guidance_scale", "num_inference_steps", "cot",
                "generated_at", "source")
        meta_lines = [f"{k}: {meta[k]}" for k in keep if k in meta]
        if meta_lines:
            parts.append("# Meta\n\n" + "\n".join(meta_lines))

    description = "\n\n".join(parts) if parts else f"{display_title}\n\n[No info.md found]"

    # Defensive: even though Style/Lyrics rarely contain angle brackets,
    # strip them just in case (YouTube rejects descriptions containing < or >)
    description = description.replace("<", "(").replace(">", ")")

    # Enforce 5000-byte limit, truncate on a UTF-8 boundary
    MAX_BYTES = 4950
    encoded = description.encode("utf-8")
    if len(encoded) > MAX_BYTES:
        cut = MAX_BYTES - 80
        while cut > 0:
            try:
                description = encoded[:cut].decode("utf-8")
                break
            except UnicodeDecodeError:
                cut -= 1
        description = description.rstrip() + "\n\n[…truncated to fit YouTube's 5000-byte limit]"

    tags = ["AI Music", "YuE2", "Original Song"]
    if style:
        extra = [t.strip() for t in style.replace(";", ",").split(",") if t.strip()]
        tags.extend(extra[:12])

    return {"title": display_title, "description": description, "tags": tags[:15]}


# ================================================================
# Score comment (Base64)
# ================================================================

def build_score_comment_body(abc_text: str) -> Optional[str]:
    """
    Build the comment body: Base64-encoded ABC with a short header.
    Returns None if the ABC is empty or the encoded result exceeds the 10,000-char limit.
    """
    if not abc_text or not abc_text.strip():
        return None

    b64 = base64.b64encode(abc_text.encode("utf-8")).decode("ascii")

    # 10,000-char limit for comments. Leave room for header + newlines.
    # 76-char wrapping adds ~1 newline per 76 chars of Base64.
    wrapped = textwrap.fill(b64, width=76)

    header = (
        "# Score (ABC notation, Base64)\n"
        "Decode to reconstruct the sheet music for this track."
    )
    body = f"{header}\n\n{wrapped}"

    if len(body) > 9900:
        console.print(
            f"  [yellow]⚠️ Base64 score would be {len(body)} chars — exceeds comment limit.[/yellow]"
        )
        return None

    return body


def post_score_comment(youtube, video_id: str, abc_text: str) -> Optional[str]:
    """
    Post the ABC score as a top-level comment.
    Returns the comment_id on success, None on failure.
    """
    body_text = build_score_comment_body(abc_text)
    if not body_text:
        return None

    try:
        response = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": body_text,
                        }
                    },
                }
            },
        ).execute()
        return response["id"]
    except HttpError as e:
        console.print(f"  [yellow]⚠️ Could not post score comment: {e}[/yellow]")
        return None
    except Exception as e:
        console.print(f"  [yellow]⚠️ Comment error: {e}[/yellow]")
        return None


# ================================================================
# Single-song upload
# ================================================================

def upload_single_song(youtube, song_dir: Path, privacy_status: str = "public",
                       force: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    slug = song_dir.name
    receipt_file = song_dir / f"{slug}-receipt.json"
    video_file = song_dir / f"{slug}.mp4"
    thumbnail_file = song_dir / f"{slug}-thumbnail.png"
    info_file = next((f for f in song_dir.glob("*-info.md")), None)

    if not video_file.exists():
        return {"status": "skipped_no_video", "title": slug}

    if receipt_file.exists() and not force:
        try:
            receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            return {"status": "already_uploaded", "title": slug,
                    "video_id": receipt.get("video_id"), "url": receipt.get("url")}
        except Exception:
            pass

    meta = build_metadata(song_dir, slug)
    abc_text = parse_score(info_file) if info_file and info_file.exists() else None

    if dry_run:
        byte_len = len(meta["description"].encode("utf-8"))
        has_score = bool(abc_text and abc_text.strip())
        score_b64_len = len(base64.b64encode(abc_text.encode("utf-8"))) if has_score else 0
        return {
            "status": "dry_run",
            "title": slug,
            "would_upload_title": meta["title"],
            "desc_chars": len(meta["description"]),
            "desc_bytes": byte_len,
            "has_score": has_score,
            "score_b64_len": score_b64_len,
        }

    console.print(f"\n[bold white]🚀 Uploading:[/] [cyan]{slug}[/cyan]")
    console.print(f"  [dim]Title:[/] \"[bold white]{meta['title']}[/bold white]\"")
    console.print(
        f"  [dim]Description:[/] {len(meta['description'])} chars "
        f"({len(meta['description'].encode('utf-8'))} bytes)"
    )

    body = {
        "snippet": {"title": meta["title"], "description": meta["description"],
                    "tags": meta["tags"], "categoryId": "10"},
        "status": {"privacyStatus": privacy_status.lower(), "selfDeclaredMadeForKids": False},
    }

    try:
        media = MediaFileUpload(str(video_file), chunksize=1024 * 1024 * 4, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        with Progress(TextColumn("[bold cyan]{task.description}[/]"),
                      BarColumn(bar_width=30), TimeRemainingColumn(),
                      console=console) as progress:
            task = progress.add_task("Uploading bytes...", total=100)
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress.update(task, completed=int(status.progress() * 100))
            video_id = response.get("id")

        url = f"https://youtu.be/{video_id}"
        console.print(f"  [bold green]✓ Uploaded:[/] [link={url}]{url}[/link]")

        # --- Thumbnail ---
        if thumbnail_file.exists():
            try:
                console.print("  [cyan]• Setting thumbnail...[/cyan]")
                youtube.thumbnails().set(
                    videoId=video_id, media_body=MediaFileUpload(str(thumbnail_file))
                ).execute()
                console.print("  [green]✓ Thumbnail set.[/green]")
            except Exception as e:
                console.print(f"  [yellow]⚠️ Thumbnail failed: {e}[/yellow]")

        # --- Score comment (Base64) ---
        comment_id = None
        if abc_text and abc_text.strip():
            console.print("  [cyan]• Posting ABC score as comment (Base64)...[/cyan]")
            comment_id = post_score_comment(youtube, video_id, abc_text)
            if comment_id:
                console.print(f"  [green]✓ Comment posted[/green] [dim](id={comment_id})[/dim]")
            else:
                console.print("  [yellow]⚠️ Comment skipped — video uploaded without score[/yellow]")
        else:
            console.print("  [dim]ℹ️ No ABC score found in info.md — skipping comment[/dim]")

        # --- Receipt ---
        receipt_data = {
            "song_slug": slug,
            "video_id": video_id,
            "url": url,
            "privacy": privacy_status,
            "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if comment_id:
            receipt_data["comment_id"] = comment_id
        receipt_file.write_text(json.dumps(receipt_data, indent=2), encoding="utf-8")

        return {"status": "uploaded", "title": slug, "video_id": video_id,
                "url": url, "comment_id": comment_id}

    except HttpError as e:
        msg = str(e)
        if "quotaExceeded" in msg:
            console.print("  [bold red]❌ Daily YouTube quota exceeded.[/bold red]")
            return {"status": "quota_exceeded", "title": slug, "error": msg}
        console.print(f"  [bold red]❌ API Error on '{slug}':[/bold red] {e}")
        return {"status": "failed", "title": slug, "error": msg}
    except Exception as e:
        console.print(f"  [bold red]❌ Error on '{slug}':[/bold red] {e}")
        return {"status": "failed", "title": slug, "error": str(e)}


# ================================================================
# Batch runner
# ================================================================

def run_youtube_uploader(song_slug: Optional[str] = None, privacy_status: str = "public",
                         force: bool = False, dry_run: bool = False) -> None:
    console.print(Panel.fit(
        f"[bold cyan]YouTube Uploader[/bold cyan]\n"
        f"[dim]Privacy: [bold yellow]{privacy_status.upper()}[/bold yellow]  •  "
        f"Description: Style + Lyrics + Meta  •  Comment: ABC Score (Base64)"
        f"{'  |  DRY RUN' if dry_run else ''}[/dim]",
        border_style="magenta",
    ))

    youtube = None if dry_run else get_youtube_client()

    if song_slug:
        target = SONGS_DIR / song_slug
        if not target.is_dir():
            console.print(f"[bold red]❌ Folder not found:[/] {target}"); return
        targets = [target]
    else:
        targets = sorted(p for p in SONGS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))

    if not targets:
        console.print("[yellow]⚠️ No song folders.[/yellow]"); return

    results = []
    for folder in targets:
        r = upload_single_song(youtube, folder, privacy_status=privacy_status,
                               force=force, dry_run=dry_run)
        results.append(r)
        if r["status"] == "quota_exceeded":
            console.print("[bold yellow]⚠️ Quota exceeded — stopping remaining uploads. Resume tomorrow.[/bold yellow]")
            break

    t = Table(title="📺 YouTube Upload Summary", box=box.ROUNDED, header_style="bold cyan")
    t.add_column("Song", style="bold white")
    t.add_column("Status")
    t.add_column("Info")

    for r in results:
        s = r["status"]
        if s == "uploaded":
            tag = "[green]Uploaded[/green]"
            if r.get("comment_id"):
                tag += " [dim]+score[/dim]"
            t.add_row(r["title"], tag, f"[link={r['url']}]{r['url']}[/link]")
        elif s == "already_uploaded":
            t.add_row(r["title"], "[cyan]Already Uploaded[/cyan]", f"[dim]{r.get('url', '—')}[/dim]")
        elif s == "dry_run":
            score_info = (
                f"score: {r['score_b64_len']} b64 chars"
                if r.get("has_score") else "no score"
            )
            t.add_row(
                r["title"], "[yellow]Dry Run[/yellow]",
                f"[white]{r['would_upload_title']}[/white] "
                f"[dim]({r['desc_chars']} chars, {r['desc_bytes']} bytes · {score_info})[/dim]",
            )
        elif s == "skipped_no_video":
            t.add_row(r["title"], "[dim]No MP4[/dim]", "[dim]Run video first[/dim]")
        elif s == "quota_exceeded":
            t.add_row(r["title"], "[red]Quota Exceeded[/red]", "[dim]Resume tomorrow[/dim]")
        else:
            t.add_row(r["title"], f"[red]{s}[/red]", f"[dim]{r.get('error', '—')[:40]}[/dim]")

    console.print("\n"); console.print(t)