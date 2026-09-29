"""Stage 1 — GPU check, system deps, secrets, fonts, audio.cpp binary download."""
import os
import sys
import shutil
import subprocess


JETBRAINS_FONTS = [
    ("JetBrainsMono-Bold.ttf",
     "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/v2.304/fonts/ttf/JetBrainsMono-Bold.ttf"),
    ("JetBrainsMono-Regular.ttf",
     "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/v2.304/fonts/ttf/JetBrainsMono-Regular.ttf"),
]
FONT_DIR = "/kaggle/working/fonts"


def _run(cmd, shell=False, check=True):
    """Run a command, streaming output to the notebook."""
    return subprocess.run(cmd, shell=shell, check=check)


def _check_gpu():
    import torch

    print("--- Checking GPU Configuration ---")
    n = torch.cuda.device_count()
    if n > 0:
        print(f"✅ Detected {n} GPU(s):")
        for i in range(n):
            print(f"  • GPU {i}: {torch.cuda.get_device_name(i)}")
    else:
        raise RuntimeError(
            "❌ GPU not enabled! Kaggle Settings → Accelerator → 'GPU T4 x2'."
        )

    from stages import state
    state.AVAILABLE_GPUS = n


def _install_system_deps():
    print("\n--- Installing system dependencies ---")
    _run([
        "bash", "-c",
        "apt-get update -qq && apt-get install -y -qq "
        "libsndfile1 ffmpeg fonts-dejavu-core fonts-dejavu-extra",
    ])
    _run([sys.executable, "-m", "pip", "install", "-q", "titlecase"])
    print("✅ System deps + titlecase installed.")


def _install_fonts():
    """Download JetBrains Mono Bold + Regular to /kaggle/working/fonts/."""
    print("\n--- Installing JetBrains Mono font ---")
    os.makedirs(FONT_DIR, exist_ok=True)

    for name, url in JETBRAINS_FONTS:
        dst = os.path.join(FONT_DIR, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            print(f"  ✓ {name} (already present)")
            continue
        try:
            _run(["wget", "-q", "-O", dst, url])
            size_kb = os.path.getsize(dst) / 1024
            print(f"  ✓ {name} ({size_kb:.0f} KB)")
        except Exception as e:
            print(f"  ⚠️ Could not fetch {name}: {e}")

    print(f"✅ Fonts ready in {FONT_DIR}")


def _load_secrets():
    from kaggle_secrets import UserSecretsClient
    from stages import state

    print("\n--- Loading secrets ---")
    secrets = UserSecretsClient()

    state.HF_TOKEN = secrets.get_secret("HF_TOKEN").strip()
    try:
        state.HF_REPO = secrets.get_secret("HF_REPO").strip()
    except Exception:
        raise SystemExit(
            "❌ HF_REPO not found in Kaggle Secrets. "
            "Add-ons → Secrets → add HF_REPO=<your_username>/<your_dataset>."
        )

    print(f" • HF vault: {state.HF_REPO}")


def _register_shared_path():
    from stages import state

    shared_dir = os.path.join(state.REPO_DIR, "notebook", "shared")
    if not os.path.isdir(shared_dir):
        raise RuntimeError(f"❌ Shared module folder missing: {shared_dir}")

    if shared_dir not in sys.path:
        sys.path.insert(0, shared_dir)
    state.SHARED_DIR = shared_dir
    print(f" • Shared modules: {shared_dir}")


def _download_audio_cpp():
    from stages import state

    if os.path.exists(state.BASE_DIR):
        shutil.rmtree(state.BASE_DIR)
    os.makedirs(state.BASE_DIR, exist_ok=True)
    os.chdir(state.BASE_DIR)

    url = (
        "https://github.com/0xShug0/audio.cpp/releases/download/"
        "v0.8.2-audio8-perf-hotfix/"
        "audio-v0.8.2-audio8-perf-hotfix-bin-ubuntu-x64-cuda12.8-colab.tar.gz"
    )
    tarball = "audio-cpp-colab.tar.gz"

    print("\n--- Downloading audio.cpp binary ---")
    _run(["wget", "-q", "-O", tarball, url])
    _run(["tar", "-xzf", tarball])
    os.remove(tarball)

    for f in ("audiocpp_server", "audiocpp_cli"):
        p = os.path.join(state.BASE_DIR, f)
        if os.path.exists(p):
            os.chmod(p, 0o755)

    if not os.path.exists(os.path.join(state.BASE_DIR, "audiocpp_server")):
        raise RuntimeError("❌ Extraction failed: 'audiocpp_server' not found.")


def run():
    _check_gpu()
    _install_system_deps()
    _install_fonts()
    _load_secrets()
    _register_shared_path()
    _download_audio_cpp()
    print("\n✅ Stage 1 Complete!")