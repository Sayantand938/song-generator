"""Stage 6 — Render videos, bundle per-song ZIPs, sync to HF in one commit."""
import os
import glob
import json
import time
import zipfile


def run():
    from stages import state
    from thumbnail import create_thumbnail
    from video_encode import encode_video
    from huggingface_hub import HfApi, CommitOperationAdd

    hf_api = HfApi(token=state.HF_TOKEN)
    wav_files = sorted(glob.glob(os.path.join(state.OUTPUT_DIR, "*.wav")))

    if not wav_files:
        print("ℹ️ No WAV files found in output directory.")
        return

    print(f"🎬 Found {len(wav_files)} track(s) to bundle...\n")

    skipped = []
    packaged = []  # list of slugs successfully zipped

    for wav_path in wav_files:
        slug = os.path.basename(wav_path).replace(".wav", "")
        score_path = os.path.join(state.OUTPUT_DIR, f"{slug}-score.abc")
        meta_path = os.path.join(state.OUTPUT_DIR, f"{slug}-meta.json")
        thumb_path = os.path.join(state.OUTPUT_DIR, f"{slug}-thumbnail.png")
        mp4_path = os.path.join(state.OUTPUT_DIR, f"{slug}.mp4")
        zip_path = os.path.join(state.OUTPUT_DIR, f"{slug}.zip")

        print(f"  🎨 Thumbnail: '{slug}-thumbnail.png'")
        try:
            create_thumbnail(slug, thumb_path)
        except Exception as e:
            print(f"  ❌ Thumbnail failed for '{slug}': {e}\n")
            skipped.append(slug)
            continue

        print(f"  🎥 Encoding MP4: '{slug}.mp4'")
        if not encode_video(wav_path, thumb_path, mp4_path):
            print(f"  ❌ FFmpeg failed for '{slug}' — skipping.\n")
            skipped.append(slug)
            continue

        # Build per-song ZIP (MP4 + PNG stored, ABC + meta deflated)
        with zipfile.ZipFile(zip_path, "w") as zf:
            for p in (mp4_path, thumb_path, score_path, meta_path):
                if os.path.exists(p):
                    ext = os.path.splitext(p)[1].lower()
                    method = zipfile.ZIP_STORED if ext in (".mp4", ".png") else zipfile.ZIP_DEFLATED
                    zf.write(p, arcname=os.path.basename(p), compress_type=method)

        zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"  ✅ Bundled → '{slug}.zip' ({zip_mb:.1f} MB)\n")
        packaged.append(slug)

    if not packaged:
        print("⚠️ No tracks were successfully bundled — nothing uploaded.")
        return

    # --- Build updated ledger ---
    with open(state.jobs_path, "r", encoding="utf-8") as f:
        raw_jobs = json.load(f)
    jobs_list = raw_jobs.get("jobs", []) if isinstance(raw_jobs, dict) else raw_jobs

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    updated = []
    for j in jobs_list:
        slug = j.get("job_id")
        if slug in skipped:
            j["status"] = "failed"
            j["error"] = "video_encoding_failed"
            j["completed_at"] = now
        elif slug in packaged and j.get("status") in ("audio_generated", "pending"):
            j["status"] = "completed"
            j["completed_at"] = now
            j = {k: v for k, v in j.items() if k not in ("style", "lyrics")}
        updated.append(j)

    ledger_bytes = json.dumps({"updated_at": now, "jobs": updated}, indent=2).encode("utf-8")

    # --- ONE atomic commit: all per-song ZIPs + ledger ---
    ops = []
    for slug in packaged:
        zp = os.path.join(state.OUTPUT_DIR, f"{slug}.zip")
        if os.path.exists(zp):
            ops.append(CommitOperationAdd(
                path_or_fileobj=zp,
                path_in_repo=f"outputs/{slug}.zip",
            ))
    ops.append(CommitOperationAdd(
        path_or_fileobj=ledger_bytes,
        path_in_repo="queue/jobs.json",
    ))

    print(f"📤 Uploading {len(packaged)} ZIP(s) + ledger to HF in 1 atomic commit...")
    hf_api.create_commit(
        repo_id=state.HF_REPO,
        repo_type="dataset",
        operations=ops,
        commit_message=f"Sync {len(packaged)} song bundle(s) + updated ledger",
    )
    print("✅ Atomic HF sync complete!")

    # Local cleanup
    for slug in packaged + skipped:
        for p in (
            os.path.join(state.OUTPUT_DIR, f"{slug}.zip"),
            os.path.join(state.OUTPUT_DIR, f"{slug}.mp4"),
            os.path.join(state.OUTPUT_DIR, f"{slug}-thumbnail.png"),
            os.path.join(state.OUTPUT_DIR, f"{slug}-score.abc"),
            os.path.join(state.OUTPUT_DIR, f"{slug}-meta.json"),
        ):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    print(f"✅ Stage 6 Complete — {len(packaged)} bundle(s) pushed, "
          f"{len(skipped)} skipped. Run `python main.py collect` locally.")