import json
import re
import time
from typing import Optional, List, Dict
from openai import OpenAI
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from src.config import (
    AICREDITS_API_KEY,
    AICREDITS_BASE_URL,
    DEFAULT_MODEL,
    TEMPERATURE,
    SONGS_DIR,
    LYRICS_MAX_CHARS,
    LYRICS_MAX_LINES,
)
from src.utils import slugify, has_audio_file, load_system_prompt

console = Console()


def get_llm_client() -> OpenAI:
    if not AICREDITS_API_KEY or AICREDITS_API_KEY == "sk-your-actual-api-key-here":
        console.print(
            Panel(
                "[bold red]Missing API Key![/bold red]\n"
                "Please configure [yellow]AICREDITS_API_KEY[/yellow] in your [cyan].env[/cyan] file.",
                border_style="red",
            )
        )
        raise SystemExit(1)
    return OpenAI(base_url=AICREDITS_BASE_URL, api_key=AICREDITS_API_KEY)


def pass_one_generate_concepts(client: OpenAI, theme: Optional[str] = None, count: int = 3,
                               model: str = DEFAULT_MODEL) -> List[dict]:
    """Generate exactly `count` concepts — one per song (1:1 mapping)."""
    start_time = time.time()

    if theme:
        status_msg = f"[bold cyan]Pass 1:[/] Brainstorming {count} concept(s) for: [yellow]'{theme}'[/yellow]..."
        direction = f'Generate {count} diverse song concepts exploring different musical angles around this theme: "{theme}".'
    else:
        status_msg = f"[bold cyan]Pass 1:[/] Autonomously inventing {count} concept(s) with [yellow]{model}[/yellow]..."
        direction = (
            f"Invent {count} distinct, fresh, and unexpected song concept(s) completely from scratch. "
            "Ensure they span across different genres (e.g., indie-folk, cinematic dark pop, alt-rock, synthwave, R&B), "
            "with evocative emotional themes and strong storytelling hooks.",
        )

    with console.status(status_msg, spinner="dots"):
        prompt = f"""
{direction}

Respond ONLY with a valid raw JSON array of exactly {count} object(s) formatted as follows:
[
  {{
    "title": "Song Title",
    "genre": "Genre, mood, and production style",
    "theme": "Core narrative arc, emotional hook, and visual imagery"
  }}
]
"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.85,
        )
        raw_text = response.choices[0].message.content.strip()

        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```\s*$", "", raw_text).strip()

        try:
            concepts = json.loads(raw_text)
            if not isinstance(concepts, list):
                concepts = [concepts]
        except json.JSONDecodeError:
            concepts = [
                {"title": f"Song Concept {i+1}", "genre": "Alternative Rock",
                 "theme": theme or "A reflective and atmospheric journey"}
                for i in range(count)
            ]

    # Trim or pad to exactly `count`
    concepts = concepts[:count]
    while len(concepts) < count:
        idx = len(concepts) + 1
        concepts.append({
            "title": f"Song Concept {idx}",
            "genre": "Alternative Rock",
            "theme": theme or "A reflective and atmospheric journey",
        })

    elapsed = round(time.time() - start_time, 2)
    table = Table(
        title=f"✨ Generated {len(concepts)} Song Direction(s) (Pass 1 - {elapsed}s)",
        show_header=True, header_style="bold magenta", box=box.ROUNDED,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="bold cyan", width=24)
    table.add_column("Genre & Production", style="green", width=30)
    table.add_column("Narrative Arc", style="white")

    for idx, c in enumerate(concepts, start=1):
        table.add_row(str(idx), c.get("title"), c.get("genre"), c.get("theme"))

    console.print(table)
    return concepts


def pass_two_generate_song(client: OpenAI, concept: dict, model: str = DEFAULT_MODEL) -> Optional[Dict]:
    system_prompt = load_system_prompt()
    title = concept.get("title", "unnamed-song")
    kebab_title = slugify(title)
    target_folder = SONGS_DIR / kebab_title

    # Duplicate slug check (skip with warning)
    if target_folder.is_dir():
        if has_audio_file(target_folder):
            return None  # silently skip — already fully generated
        existing_info = next((f for f in target_folder.iterdir() if f.name.endswith("-info.md")), None)
        if existing_info:
            console.print(
                f"  [bold yellow]⚠️ Skipped '{title}':[/] slug '[cyan]{kebab_title}[/cyan]' already exists "
                f"(no audio yet). Pick a different title or delete the folder to regenerate."
            )
            return None

    user_prompt = f"""
Write a complete song based on this chosen concept:
- Title: {title}
- Style/Genre: {concept.get('genre')}
- Theme/Narrative: {concept.get('theme')}

Follow all rules in your system prompt. Output strictly starting with # Style followed by # Lyrics.
"""

    start_time = time.time()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=TEMPERATURE,
        stream=False,
    )

    full_output = response.choices[0].message.content.strip()
    full_output = re.sub(r"^```(?:markdown)?\s*\n?", "", full_output, flags=re.IGNORECASE)
    full_output = re.sub(r"\n?```\s*$", "", full_output).strip()
    elapsed = round(time.time() - start_time, 2)

    # Length sanity check
    lyrics_match = re.search(r"#+\s*Lyrics\s*\n(.*)", full_output, re.DOTALL | re.IGNORECASE)
    if lyrics_match:
        lyrics_text = lyrics_match.group(1).strip()
        char_count = len(lyrics_text)
        line_count = len([l for l in lyrics_text.split("\n") if l.strip()])
        if char_count > LYRICS_MAX_CHARS:
            console.print(
                f"  [yellow]⚠️ '{title}': lyrics are long ({char_count} chars > {LYRICS_MAX_CHARS}). "
                f"YuE2 may truncate.[/yellow]"
            )
        if line_count > LYRICS_MAX_LINES:
            console.print(
                f"  [yellow]⚠️ '{title}': lyrics have many lines ({line_count} > {LYRICS_MAX_LINES}).[/yellow]"
            )

    target_folder.mkdir(parents=True, exist_ok=True)
    output_filepath = target_folder / f"{kebab_title}-info.md"
    output_filepath.write_text(full_output + "\n", encoding="utf-8")

    return {
        "title": title,
        "genre": concept.get("genre"),
        "path": f"songs/{kebab_title}/",
        "file": str(output_filepath),
        "elapsed": elapsed,
    }


def run_lyricist(count: int = 3, theme: Optional[str] = None, model: str = DEFAULT_MODEL) -> None:
    client = get_llm_client()

    console.print(
        Panel.fit(
            f"[bold cyan]Songwriting Assistant[/bold cyan]\n"
            f"[dim]Batch Mode: {count} Song(s)  •  1 concept per song  •  Model: {model}[/dim]",
            border_style="blue",
        )
    )

    concepts = pass_one_generate_concepts(client=client, theme=theme, count=count, model=model)
    console.print("\n[bold cyan]Pass 2:[/] Writing song arrangements & lyrics...\n")
    completed_songs = []

    with Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Writing tracks...", total=len(concepts))

        for idx, concept in enumerate(concepts, start=1):
            title = concept.get("title", f"Track {idx}")
            progress.update(task, description=f"[{idx}/{count}] Writing '[bold white]{title}[/]'")
            try:
                res = pass_two_generate_song(client=client, concept=concept, model=model)
                if res:
                    completed_songs.append(res)
                    progress.console.print(
                        f"  [bold green]✓ Saved:[/] [cyan]{res['file']}[/cyan] [dim]({res['elapsed']}s)[/dim]"
                    )
            except Exception as e:
                progress.console.print(f"  [bold red]❌ Error generating '{title}':[/] {e}")
            progress.advance(task)

    console.print("\n")
    if completed_songs:
        summary_table = Table(
            title=f"🎉 Successfully Generated {len(completed_songs)} of {count} Track(s)",
            box=box.ROUNDED, header_style="bold green",
        )
        summary_table.add_column("#", justify="center", style="dim", width=4)
        summary_table.add_column("Title", style="bold white", width=26)
        summary_table.add_column("Genre", style="cyan", width=30)
        summary_table.add_column("Folder Location", style="dim")

        for i, s in enumerate(completed_songs, start=1):
            summary_table.add_row(str(i), s["title"], s["genre"], s["path"])

        console.print(summary_table)
        console.print("\n[bold green]🚀 Ready for audio rendering![/bold green]")
        console.print("  • [cyan]Kaggle Cloud:[/cyan] Run [bold white]python main.py dispatch[/bold white]")
        console.print("  • [magenta]Local Engine:[/magenta] Run [bold white]python main.py local[/bold white]\n")
    else:
        console.print("[bold yellow]⚠️ No new tracks were saved.[/]")