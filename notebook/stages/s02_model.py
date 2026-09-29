"""Stage 2 — Download YuE2 weights and write server configs."""
import os
import json
import shutil


def _download_weights():
    from stages import state
    from huggingface_hub import hf_hub_download

    model_dir = os.path.join(state.BASE_DIR, "models", "yue2")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(os.path.join(model_dir, "sidecars"), exist_ok=True)

    mounted = "/kaggle/input/yue2-weights"
    if os.path.exists(os.path.join(mounted, "yue2-3b-q8_0.gguf")):
        print("⚡ Found pre-mounted weights — skipping download.")
        state.MODEL_DIR = mounted
        return

    repo_id = "audio-cpp/Yue2-3B-GGUF"
    files = [
        "yue2-3b-q8_0.gguf",
        "yue2-vae-f16.gguf",
        "sidecars/yue2-generation-config.json",
        "sidecars/yue2-model-config.json",
        "sidecars/yue2-qwen.tiktoken",
        "sidecars/yue2-vae-config.json",
    ]

    print("--- Downloading YuE2 weights from Hugging Face ---")
    for rel in files:
        try:
            hf_hub_download(
                repo_id=repo_id, filename=rel,
                local_dir=model_dir, token=state.HF_TOKEN,
            )
        except Exception:
            hf_hub_download(
                repo_id=repo_id, filename=os.path.basename(rel),
                local_dir=model_dir, token=state.HF_TOKEN,
            )

    # Move sidecars into place if they landed at root
    for name in ("yue2-generation-config.json", "yue2-model-config.json",
                 "yue2-qwen.tiktoken", "yue2-vae-config.json"):
        want = os.path.join(model_dir, "sidecars", name)
        have = os.path.join(model_dir, name)
        if not os.path.exists(want) and os.path.exists(have):
            shutil.copy2(have, want)

    assert os.path.exists(os.path.join(model_dir, "yue2-3b-q8_0.gguf")), \
        "❌ Missing model GGUF!"
    assert os.path.exists(os.path.join(model_dir, "yue2-vae-f16.gguf")), \
        "❌ Missing VAE GGUF!"

    state.MODEL_DIR = model_dir


def _write_server_configs():
    from stages import state

    def make_config(port):
        return {
            "host": "127.0.0.1",
            "port": port,
            "backend": "cuda",
            "threads": 4,
            "lazy_load": False,
            "models": [{
                "id": "yue2-music",
                "family": "yue2",
                "task": "gen",
                "path": state.MODEL_DIR,
                "session_options": {
                    "yue2.model_gguf": "yue2-3b-q8_0.gguf",
                    "yue2.vae_gguf": "yue2-vae-f16.gguf",
                    "yue2.cot": "full",
                    "yue2.num_inference_steps": 32,
                },
            }],
        }

    for port, name in ((8080, "server_gpu0.json"), (8081, "server_gpu1.json")):
        path = os.path.join(state.BASE_DIR, name)
        with open(path, "w") as f:
            json.dump(make_config(port), f, indent=2)


def run():
    _download_weights()
    _write_server_configs()
    print("✅ Stage 2 Complete — server configs written for ports 8080, 8081.")