import json
import os
import shutil
import tempfile
import time
import zipfile
from typing import Optional, List, Dict, Any

from huggingface_hub import (
    HfApi, hf_hub_download, CommitOperationDelete, CommitOperationAdd,
)

from src.config import HF_TOKEN, HF_REPO, SONGS_DIR
from src.utils import log, parse_info_md, has_audio_file, append_score_and_meta


# ================================================================
# Remote ledger helpers
# ================================================================

def _get_hf_api() -> HfApi:
    if not HF_TOKEN:
        log("❌ HF_TOKEN is missing in your .env file!")
        raise SystemExit(1)
    if not HF_REPO:
        log("❌ HF_REPO is missing in your .env file!")
        raise SystemExit(1)
    return HfApi(token=HF_TOKEN)


def _fetch_remote_jobs() -> List[Dict[str, Any]]:
    try:
        local = hf_hub_download(
            repo_id=HF_REPO, filename="queue/jobs.json",
            repo_type="dataset", token=HF_TOKEN, force_download=True,
        )
        with open(local, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "jobs" in data:
            return data["jobs"]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _upload_remote_jobs(jobs: List[Dict[str, Any]], commit_message: str) -> None:
    payload = {"updated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "jobs": jobs}
    raw = json.dumps(payload, indent=2).encode("utf-8")
    _get_hf_api().upload_file(
        path_or_fileobj=raw, path_in_repo="queue/jobs.json",
        repo_id=HF_REPO, repo_type="dataset", commit_message=commit_message,
    )


def _prune_completed(job: Dict[str, Any]) -> Dict[str, Any]:
    if job.get("status") == "completed":
        return {k: v for k, v in job.items() if k not in ("style", "lyrics")}
    return job


# ================================================================
# Public commands
# ================================================================

def dispatch_queue(seed: Optional[int] = None, dry_run: bool = False) -> None:
    log("=" * 50)
    log(" 🛫 Dispatcher (HF Vault)")
    log("=" * 50)

    hf_api = _get_hf_api()
    existing_jobs = _fetch_remote_jobs()
    existing_by_slug = {j.get("job_id"): j for j in existing_jobs}

    log(f"Remote ledger currently holds {len(existing_jobs)} job(s).")
    log(f"Scanning local library: {SONGS_DIR}")

    candidates = []
    for folder in sorted(SONGS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        slug = folder.name

        info_file = next((f for f in folder.iterdir() if f.name.endswith("-info.md")), None)
        if not info_file:
            continue
        if has_audio_file(folder):
            continue

        existing = existing_by_slug.get(slug)
        if existing and existing.get("status") in ("pending", "audio_generated", "completed"):
            log(f"⏭️  Skipping '{slug}': already on HF (status={existing['status']}).")
            continue

        style, lyrics = parse_info_md(info_file)
        if not style or not lyrics:
            log(f"⚠️ Skipping '{slug}': could not parse style/lyrics.")
            continue

        candidates.append({"slug": slug, "style": style, "lyrics": lyrics})

    if not candidates:
        log("🎉 No new songs to dispatch.")
        return

    base_seed = seed if seed is not None else int(time.time())
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    new_jobs = []
    for i, c in enumerate(candidates):
        new_jobs.append({
            "job_id": c["slug"],
            "style": c["style"],
            "lyrics": c["lyrics"],
            "status": "pending",
            "seed": base_seed + i,
            "dispatched_at": now,
        })

    log(f"📋 New songs to dispatch: {len(new_jobs)}")
    for j in new_jobs:
        log(f"   • {j['job_id']} (seed={j['seed']})")

    if dry_run:
        log("🔍 DRY RUN — nothing uploaded.")
        return

    new_slugs = {j["job_id"] for j in new_jobs}
    merged: List[Dict[str, Any]] = []
    for old in existing_jobs:
        if old.get("job_id") in new_slugs:
            continue
        merged.append(_prune_completed(old))
    merged.extend(new_jobs)

    log(f"📤 Uploading merged ledger ({len(merged)} jobs) to HF...")
    _upload_remote_jobs(merged, f"Dispatch {len(new_jobs)} new song(s)")
    log("✅ Dispatch complete. Open Kaggle Cell 4 now.")


def retry_failed(song_slug: Optional[str] = None, dry_run: bool = False) -> None:
    log("=" * 50)
    log(" 🔁 Retry Failed Jobs")
    log("=" * 50)

    jobs = _fetch_remote_jobs()
    failed = [j for j in jobs if j.get("status") == "failed"]
    if song_slug:
        failed = [j for j in failed if j.get("job_id") == song_slug]

    if not failed:
        log("ℹ️ No failed jobs to retry.")
        return

    log(f"Found {len(failed)} failed job(s):")
    for j in failed:
        log(f"   • {j['job_id']}")

    if dry_run:
        log("🔍 DRY RUN — nothing uploaded.")
        return

    retried = 0
    for j in failed:
        slug = j["job_id"]
        folder = SONGS_DIR / slug
        info = (
            next((f for f in folder.iterdir() if f.name.endswith("-info.md")), None)
            if folder.is_dir() else None
        )
        if not info:
            log(f"⚠️ Cannot retry '{slug}': local info.md missing.")
            continue
        style, lyrics = parse_info_md(info)
        if not style or not lyrics:
            log(f"⚠️ Cannot retry '{slug}': could not parse style/lyrics.")
            continue
        j["style"] = style
        j["lyrics"] = lyrics
        j["status"] = "pending"
        j["dispatched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        for k in ("error", "wall_time", "audio_duration", "rtf", "completed_at"):
            j.pop(k, None)
        retried += 1

    if retried == 0:
        log("❌ No jobs could be rehydrated — nothing uploaded.")
        return

    _upload_remote_jobs(jobs, f"Retry {retried} failed job(s)")
    log(f"✅ {retried} job(s) reset to pending.")


def collect_songs() -> None:
    """Download per-song ZIPs from HF, extract into songs/<slug>/, merge score+meta, delete remote ZIPs.

    Safety: ZIPs that don't map to a local song folder are LEFT ON HF
    (not deleted) so nothing is lost when the local library is out of sync.
    """
    log("=" * 50)
    log(" 📥 Collecting Song Bundles from Hugging Face Vault")
    log("=" * 50)

    hf_api = _get_hf_api()
    try:
        repo_files = hf_api.list_repo_files(repo_id=HF_REPO, repo_type="dataset")
    except Exception as e:
        log(f"❌ Failed to connect to '{HF_REPO}': {e}")
        return

    zip_files = [f for f in repo_files if f.startswith("outputs/") and f.lower().endswith(".zip")]
    if not zip_files:
        log("ℹ️ No bundles waiting in vault.")
        return

    log(f"🔍 Found {len(zip_files)} bundle(s) ready to download.")
    collected = []   # only ZIPs that were successfully extracted locally
    left_on_hf = []  # ZIPs skipped (no matching local folder)

    for remote_zip in zip_files:
        zip_name = os.path.basename(remote_zip)
        slug = os.path.splitext(zip_name)[0]  # <slug>.zip → <slug>
        log(f"\n📦 Processing bundle: {zip_name}")

        # --- SAFETY: bail out early if there's no matching local folder ---
        target = SONGS_DIR / slug
        if not target.is_dir():
            log(f"  ⚠️ No local folder for '{slug}' — leaving ZIP on HF.")
            left_on_hf.append(zip_name)
            continue

        try:
            with tempfile.TemporaryDirectory() as tmp:
                local_zip = hf_hub_download(
                    repo_id=HF_REPO, filename=remote_zip, repo_type="dataset",
                    token=HF_TOKEN, local_dir=tmp, force_download=True,
                )

                with tempfile.TemporaryDirectory() as ext:
                    with zipfile.ZipFile(local_zip) as zf:
                        zf.extractall(ext)

                    # Copy MP4 + PNG
                    for asset_name in (f"{slug}.mp4", f"{slug}-thumbnail.png"):
                        src = os.path.join(ext, asset_name)
                        if os.path.exists(src):
                            shutil.copy2(src, target / asset_name)
                            log(f"  ✅ songs/{slug}/{asset_name}")

                    # Merge Score + Meta into info.md
                    abc_src = os.path.join(ext, f"{slug}-score.abc")
                    meta_src = os.path.join(ext, f"{slug}-meta.json")
                    info_path = target / f"{slug}-info.md"

                    if info_path.exists() and (os.path.exists(abc_src) or os.path.exists(meta_src)):
                        abc_text = None
                        if os.path.exists(abc_src):
                            with open(abc_src, "r", encoding="utf-8", errors="replace") as f:
                                abc_text = f.read()

                        meta_dict: Dict[str, Any] = {}
                        if os.path.exists(meta_src):
                            try:
                                with open(meta_src, "r", encoding="utf-8") as f:
                                    meta_dict = json.load(f)
                            except Exception as e:
                                log(f"  ⚠️ Meta parse failed for '{slug}': {e}")

                        append_score_and_meta(info_path, abc_text, meta_dict)
                        log(f"  ✅ Merged score + meta → songs/{slug}/{slug}-info.md")
                    elif not info_path.exists():
                        log(f"  ⚠️ Skipping score/meta for '{slug}': info.md missing locally.")

            collected.append(remote_zip)
        except Exception as e:
            log(f"❌ Error processing '{zip_name}': {e}")
            # On error, do NOT delete from HF — leave for a retry
            left_on_hf.append(zip_name)

    # --- Cleanup: delete only the ZIPs we actually extracted ---
    if collected:
        log(f"\n🧹 Deleting {len(collected)} collected bundle(s) from HF...")
        try:
            ops = [CommitOperationDelete(path_in_repo=p) for p in collected]
            hf_api.create_commit(
                repo_id=HF_REPO, repo_type="dataset",
                operations=ops,
                commit_message=f"Collected {len(collected)} bundle(s)",
            )
            log("🎉 Vault cleaned.")
        except Exception as e:
            log(f"⚠️ Remote cleanup warning: {e}")

    if left_on_hf:
        log(f"\n📌 {len(left_on_hf)} bundle(s) left on HF (no matching local folder):")
        for name in left_on_hf:
            log(f"   • {name}")
        log("   These stay in the vault until a local folder with a matching slug exists.")


def clean_vault() -> None:
    log("=" * 50)
    log(" 🧼 Hugging Face Remote Vault Cleanup")
    log("=" * 50)

    hf_api = _get_hf_api()
    log(f"Connecting to: {HF_REPO}...")

    try:
        files = hf_api.list_repo_files(repo_id=HF_REPO, repo_type="dataset")
    except Exception as e:
        log(f"❌ Failed to access repo: {e}")
        return

    operations = []
    for f in [f for f in files if f.startswith("outputs/")]:
        operations.append(CommitOperationDelete(path_in_repo=f))
        log(f"  🗑️ Queued deletion: {f}")

    operations.append(CommitOperationAdd(
        path_in_repo="queue/jobs.json",
        path_or_fileobj=b'{"jobs": []}',
    ))
    log("  📝 Resetting queue/jobs.json to empty.")

    try:
        hf_api.create_commit(
            repo_id=HF_REPO, repo_type="dataset",
            operations=operations,
            commit_message="End-of-day vault cleanup and queue reset",
        )
        log("🎉 Remote repository wiped clean and ready.")
    except Exception as e:
        log(f"❌ Cleanup failed: {e}")