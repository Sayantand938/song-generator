"""Stage 4 — Fetch the job ledger from Hugging Face and display it."""
import os
import json
import time


def run():
    from stages import state
    from huggingface_hub import hf_hub_download
    from rich import box
    from rich.console import Console
    from rich.table import Table

    console = Console(highlight=False)

    os.makedirs(state.QUEUE_DIR, exist_ok=True)
    os.makedirs(state.OUTPUT_DIR, exist_ok=True)
    state.jobs_path = os.path.join(state.QUEUE_DIR, "jobs.json")

    console.print(f" • HF target: [bold cyan]{state.HF_REPO}[/bold cyan]")

    print("\nFetching job ledger from Hugging Face...")
    try:
        downloaded = hf_hub_download(
            repo_id=state.HF_REPO,
            filename="queue/jobs.json",
            repo_type="dataset",
            token=state.HF_TOKEN,
            force_download=True,
        )
        with open(downloaded, "r", encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, dict) and "jobs" in raw:
            state.jobs = raw["jobs"]
        elif isinstance(raw, list):
            state.jobs = raw
        else:
            raise ValueError("Invalid jobs.json shape")

        print(f" • Ledger holds {len(state.jobs)} total entries.")

    except Exception as e:
        console.print(f"[red]⚠️ Could not load queue/jobs.json from {state.HF_REPO}: {e}[/red]")
        console.print("[yellow]Creating a fallback demo job.[/yellow]")
        state.jobs = [{
            "job_id": "demo-test-song",
            "style": "80s synthwave, driving bassline, retro electric drums, male vocals",
            "lyrics": ("[verse]\nDriving down the highway at midnight\n"
                       "Neon reflections in the rearview light\n"
                       "[chorus]\nWe are electric, running so fast\n"
                       "Leave all the memories in the past"),
            "status": "pending",
            "seed": 0,
        }]

    # Persist locally so s05 / s06 have a canonical file
    with open(state.jobs_path, "w", encoding="utf-8") as f:
        json.dump({"jobs": state.jobs, "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, indent=2)

    state.pending_jobs = [j for j in state.jobs if j.get("status") == "pending"]

    table = Table(
        title=f"Queue: {len(state.jobs)} total | {len(state.pending_jobs)} pending",
        box=box.ASCII_DOUBLE_HEAD,
    )
    table.add_column("Status")
    table.add_column("Job ID")
    table.add_column("Seed", justify="right")
    table.add_column("Style")

    for j in state.jobs:
        style = (j.get("style") or "[pruned]")[:45]
        table.add_row(
            j.get("status", "unknown").capitalize(),
            j.get("job_id", "N/A"),
            str(j.get("seed", "—")),
            style,
        )

    console.print(table)
    print("\n✅ Stage 4 Complete — ready to generate.")