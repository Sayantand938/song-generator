"""Stage 7 — Verify remote vault + shut down servers."""
import subprocess


def run():
    from stages import state
    from huggingface_hub import HfApi

    print("--- Final pipeline health check ---")
    hf_api = HfApi(token=state.HF_TOKEN)

    try:
        files = hf_api.list_repo_files(repo_id=state.HF_REPO, repo_type="dataset")
        bundles = [f for f in files if f.startswith("outputs/") and f.lower().endswith(".zip")]
        print(f"📦 {len(bundles)} per-song ZIP bundle(s) available on HF Hub:")
        for f in bundles:
            print(f"  • {f}")
    except Exception as e:
        print(f"⚠️ Could not query remote repo: {e}")

    print("\nShutting down audio.cpp servers...")
    subprocess.run(
        ["pkill", "-9", "-f", "audiocpp_server"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print("✅ Stage 7 Complete — servers stopped. Run `python main.py collect` locally.")