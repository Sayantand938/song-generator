import base64
import io
import requests
import time
import wave
from typing import Optional

from src.config import (
    LOCAL_SERVER_URL, SONGS_DIR,
    DEFAULT_GUIDANCE_SCALE, DEFAULT_NUM_INFERENCE_STEPS, DEFAULT_COT,
)
from src.utils import (
    log, parse_info_md, has_audio_file,
    new_batch_id, write_manifest, append_score_and_meta,
)


def check_server_health(retries: int = 6, delay: float = 5.0) -> bool:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{LOCAL_SERVER_URL}/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if attempt < retries:
            log(f"  … server not ready yet (attempt {attempt}/{retries}), retrying in {delay:.0f}s")
            time.sleep(delay)
    return False


def run_local_batch(seed: Optional[int] = None) -> None:
    log("=" * 50)
    log(" 🎸 Local YuE2 Generator (AMD RX 7800 XT - Vulkan)")
    log("=" * 50)

    log(f"Checking server status at {LOCAL_SERVER_URL}...")
    if not check_server_health():
        log(f"❌ Server is not responding at {LOCAL_SERVER_URL}!")
        log("👉 Please double-click 'Start_YuE2_Server.bat' in your audio.cpp folder first.")
        return
    log("✅ Local audio.cpp engine is online and ready!")

    log(f"Scanning library: {SONGS_DIR}")
    pending_jobs = []

    for folder in sorted(SONGS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith('.'):
            continue
        slug = folder.name
        info_file = next((f for f in folder.iterdir() if f.name.endswith("-info.md")), None)
        if not info_file:
            log(f"⚠️ Skipped '{slug}': no -info.md file.")
            continue
        if has_audio_file(folder):
            continue

        style, lyrics = parse_info_md(info_file)
        if not style or not lyrics:
            log(f"⚠️ Skipped '{slug}': could not parse style/lyrics.")
            continue

        pending_jobs.append({
            "job_id": slug, "folder": folder, "info_file": info_file,
            "style": style, "lyrics": lyrics,
        })

    if not pending_jobs:
        log("🎉 All songs already have audio. Nothing pending!")
        return

    batch_id = new_batch_id()
    base_seed = seed if seed is not None else int(time.time())

    log(f"📋 Found {len(pending_jobs)} song(s) queued for generation (batch {batch_id}).\n")

    manifest_songs = []
    for idx, job in enumerate(pending_jobs):
        slug = job["job_id"]
        job_seed = base_seed + idx
        log(f"[{idx+1}/{len(pending_jobs)}] ⏳ Starting generation: '{slug}' (seed={job_seed})...")

        payload = {
            "model": "yue2-music",
            "options": {
                "style": job["style"],
                "lyrics": job["lyrics"],
                "cot": DEFAULT_COT,
                "guidance_scale": DEFAULT_GUIDANCE_SCALE,
                "num_inference_steps": DEFAULT_NUM_INFERENCE_STEPS,
                "seed": job_seed,
            }
        }

        job_start = time.time()
        try:
            resp = requests.post(f"{LOCAL_SERVER_URL}/v1/tasks/run", json=payload, timeout=1200)
            wall_time = time.time() - job_start

            if resp.status_code == 200:
                res = resp.json()
                audio_dur = 0.0
                wav_path = job["folder"] / f"{slug}.wav"

                if res.get("audio"):
                    audio_bytes = base64.b64decode(res["audio"])
                    wav_path.write_bytes(audio_bytes)
                    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                        audio_dur = wf.getnframes() / float(wf.getframerate())

                # Extract ABC score (if returned)
                abc_text = None
                for art in res.get("artifacts", []):
                    if art.get("id") == "score":
                        abc_text = base64.b64decode(art["payload"]).decode("utf-8", errors="replace")

                # Build meta and merge into info.md
                meta = {
                    "seed": job_seed,
                    "model": "yue2-music",
                    "model_gguf": "yue2-3b-q8_0.gguf",
                    "vae_gguf": "yue2-vae-f16.gguf",
                    "guidance_scale": DEFAULT_GUIDANCE_SCALE,
                    "num_inference_steps": DEFAULT_NUM_INFERENCE_STEPS,
                    "cot": DEFAULT_COT,
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "local",
                }
                append_score_and_meta(job["info_file"], abc_text, meta)

                rtf = wall_time / audio_dur if audio_dur > 0 else 0
                log(f"  ✅ Saved to songs/{slug}/ in {wall_time:.1f}s "
                    f"(Audio: {audio_dur:.1f}s | RTF: {rtf:.2f})\n")

                manifest_songs.append({
                    "slug": slug, "seed": job_seed, "status": "completed",
                    "wall_time": round(wall_time, 2),
                    "audio_duration": round(audio_dur, 2),
                    "rtf": round(rtf, 3),
                })
            else:
                log(f"  ❌ Server Error on '{slug}': HTTP {resp.status_code} - {resp.text}\n")
                manifest_songs.append({
                    "slug": slug, "seed": job_seed, "status": "failed",
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                })
        except Exception as e:
            log(f"  ❌ Failed to generate '{slug}': {e}\n")
            manifest_songs.append({"slug": slug, "seed": job_seed, "status": "failed", "error": str(e)})

    manifest_path = write_manifest(
        batch_id=batch_id, mode="local", songs=manifest_songs,
        guidance_scale=DEFAULT_GUIDANCE_SCALE,
        num_inference_steps=DEFAULT_NUM_INFERENCE_STEPS,
        base_seed=base_seed,
    )
    log(f"📝 Manifest saved: {manifest_path}")
    log("🎉 Finished local batch!")