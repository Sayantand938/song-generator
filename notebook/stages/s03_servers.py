"""Stage 3 — Launch audio.cpp server(s) and wait for health."""
import os
import time
import subprocess


def _decide_gpu_mode():
    from stages import state
    if state.AVAILABLE_GPUS < 2:
        if state.AVAILABLE_GPUS == 0:
            raise RuntimeError("❌ No GPUs available.")
        print(f"⚠️ Only {state.AVAILABLE_GPUS} GPU available — running single-GPU mode.")
        state.DUAL_GPU_MODE = False
    else:
        state.DUAL_GPU_MODE = True


def _kill_stale():
    subprocess.run(["pkill", "-9", "-f", "audiocpp_server"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def _wait_for_health(port, max_wait_sec=180):
    import requests
    url = f"http://127.0.0.1:{port}/health"
    start = time.time()
    while time.time() - start < max_wait_sec:
        try:
            if requests.get(url, timeout=1.5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _tail(path, lines=25):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.readlines()
        for line in content[-lines:]:
            print("   " + line.rstrip())
    except Exception:
        pass


def run():
    from stages import state

    _decide_gpu_mode()
    os.chdir(state.BASE_DIR)
    print("--- Terminating any old server instances ---")
    _kill_stale()

    servers = [{"gpu": 0, "port": 8080, "config": "server_gpu0.json", "log": "server_gpu0.log"}]
    if state.DUAL_GPU_MODE:
        servers.append({"gpu": 1, "port": 8081, "config": "server_gpu1.json", "log": "server_gpu1.log"})

    for s in servers:
        log_path = os.path.join(state.BASE_DIR, s["log"])
        log_handle = open(log_path, "w")
        print(f"  🚀 Launching server on GPU {s['gpu']} (Port {s['port']})...")

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(s["gpu"])

        proc = subprocess.Popen(
            ["./audiocpp_server", "--config", s["config"]],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
        )
        state.server_processes.append((s, proc, log_handle, log_path))

    print("\n⏳ Waiting for model weights to load into VRAM...")
    all_ok = True
    for s, proc, handle, log_path in state.server_processes:
        if _wait_for_health(s["port"]):
            print(f"  ✅ GPU {s['gpu']} (Port {s['port']}) online.")
        else:
            print(f"  ❌ GPU {s['gpu']} failed. Last 25 log lines:")
            _tail(log_path)
            all_ok = False

    if not all_ok:
        raise RuntimeError("One or more audio.cpp servers failed to start.")

    mode = "DUAL-GPU" if state.DUAL_GPU_MODE else "SINGLE-GPU"
    print(f"\n✅ Stage 3 Complete — engine ready in {mode} mode.")