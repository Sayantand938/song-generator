"""Stage 5 — Generate audio + ABC score across GPU workers."""
import os
import io
import time
import wave
import json
import base64
import queue as queue_mod
import threading
from concurrent.futures import ThreadPoolExecutor


def _worker(info, job_queue, state, print_lock, file_lock, counters):
    import requests

    gpu_id = info["gpu"]
    base_url = info["url"]

    while True:
        try:
            job = job_queue.get_nowait()
        except queue_mod.Empty:
            break

        slug = job["job_id"]
        seed = int(job.get("seed") or (int(time.time()) + gpu_id))

        with print_lock:
            print(f"\n[GPU {gpu_id}] ⏳ Generating '{slug}' (seed={seed})...")

        payload = {
            "model": "yue2-music",
            "options": {
                "style": job["style"],
                "lyrics": job["lyrics"],
                "cot": "full",
                "guidance_scale": 1.02,
                "num_inference_steps": 32,
                "seed": seed,
            },
        }

        t0 = time.time()
        try:
            r = requests.post(f"{base_url}/v1/tasks/run", json=payload, timeout=1200)
            wall = time.time() - t0

            if r.status_code == 200:
                res = r.json()
                wav_path = os.path.join(state.OUTPUT_DIR, f"{slug}.wav")
                abc_path = os.path.join(state.OUTPUT_DIR, f"{slug}-score.abc")
                meta_path = os.path.join(state.OUTPUT_DIR, f"{slug}-meta.json")
                audio_dur = 0.0

                # 1. Save WAV
                if res.get("audio"):
                    abytes = base64.b64decode(res["audio"])
                    with open(wav_path, "wb") as f:
                        f.write(abytes)
                    with wave.open(io.BytesIO(abytes), "rb") as wf:
                        audio_dur = wf.getnframes() / float(wf.getframerate() or 1)

                # 2. Save ABC score (transient — merged into info.md during collect)
                for art in res.get("artifacts", []):
                    if art.get("id") == "score":
                        with open(abc_path, "wb") as f:
                            f.write(base64.b64decode(art["payload"]))

                # 3. Save Meta JSON (transient — merged into info.md during collect)
                meta = {
                    "seed": seed,
                    "model": "yue2-music",
                    "model_gguf": "yue2-3b-q8_0.gguf",
                    "vae_gguf": "yue2-vae-f16.gguf",
                    "guidance_scale": 1.02,
                    "num_inference_steps": 32,
                    "cot": "full",
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "kaggle",
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)

                rtf = wall / audio_dur if audio_dur > 0 else 0

                with print_lock:
                    print(f"[GPU {gpu_id}] ✅ '{slug}' in {wall:.1f}s "
                          f"(audio={audio_dur:.1f}s, RTF={rtf:.2f})")

                with file_lock:
                    job["status"] = "audio_generated"
                    job["wall_time"] = round(wall, 2)
                    job["audio_duration"] = round(audio_dur, 2)
                    job["rtf"] = round(rtf, 3)
                    job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    counters["processed"] += 1
                    with open(state.jobs_path, "w", encoding="utf-8") as f:
                        json.dump({"jobs": state.jobs}, f, indent=2)
            else:
                with print_lock:
                    print(f"[GPU {gpu_id}] ❌ '{slug}' HTTP {r.status_code}: {r.text[:200]}")
                with file_lock:
                    job["status"] = "failed"
                    job["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
                    with open(state.jobs_path, "w", encoding="utf-8") as f:
                        json.dump({"jobs": state.jobs}, f, indent=2)

        except Exception as e:
            with print_lock:
                print(f"[GPU {gpu_id}] ❌ '{slug}' error: {e}")
            with file_lock:
                job["status"] = "failed"
                job["error"] = str(e)
                with open(state.jobs_path, "w", encoding="utf-8") as f:
                    json.dump({"jobs": state.jobs}, f, indent=2)
        finally:
            job_queue.task_done()


def run():
    from stages import state

    if not state.pending_jobs:
        print("🎉 No pending jobs — nothing to generate.")
        return

    endpoints = [{"gpu": 0, "url": "http://127.0.0.1:8080"}]
    if state.DUAL_GPU_MODE:
        endpoints.append({"gpu": 1, "url": "http://127.0.0.1:8081"})

    print(f"⚙️ Running generation across {len(endpoints)} GPU worker(s)...")

    job_queue = queue_mod.Queue()
    for job in state.pending_jobs:
        job_queue.put(job)

    print_lock = threading.Lock()
    file_lock = threading.Lock()
    counters = {"processed": 0}
    batch_start = time.time()

    with ThreadPoolExecutor(max_workers=len(endpoints)) as ex:
        futures = [
            ex.submit(_worker, ep, job_queue, state, print_lock, file_lock, counters)
            for ep in endpoints
        ]
        for f in futures:
            f.result()

    print(f"\n✅ Stage 5 Complete — {counters['processed']} song(s) "
          f"in {time.time() - batch_start:.1f}s.")