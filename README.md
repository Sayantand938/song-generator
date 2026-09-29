# Autonomous AI Music Studio

An end-to-end pipeline for AI music production: write lyrics with an LLM → render audio on GPU (local or Kaggle cloud) → generate 1080p YouTube videos → upload directly to YouTube.

---

## Architecture

- **`src/`** — local CLI (`write`, `local`, `video`, `upload`, `dispatch`, `collect`, `retry`, `status`, `clean`)
- **`notebook/stages/`** — one Python module per Kaggle cell; auto-synced from GitHub on every Kaggle run
- **`notebook/shared/`** — reusable helpers (thumbnail rendering with JetBrains Mono, title-casing, video encoding)

The Kaggle notebook is a thin wrapper: Cell 1 clones this repo, and every subsequent cell calls `sNN_xxx.run()` from `notebook/stages/`. Any `git push` is picked up on the next Kaggle run.

---

## File Naming Convention

Every song lives in `songs/kebab-case-name/`:

| File | Purpose |
|------|---------|
| `kebab-case-name-info.md` | **Single source of truth** — Style, Lyrics, Meta (seed + params), Score (ABC notation) |
| `kebab-case-name.wav` | Master audio |
| `kebab-case-name.mp4` | 1080p YouTube video |
| `kebab-case-name-thumbnail.png` | Title-Case thumbnail |
| `kebab-case-name-receipt.json` | YouTube upload receipt (only after `upload`) |

The `-info.md` file is structured as:

```
# Style
ambient synthwave, female vocals, minor key, ...

# Lyrics
[Verse 1]
...

# Meta
seed: 1748291034
model: yue2-music
model_gguf: yue2-3b-q8_0.gguf
vae_gguf: yue2-vae-f16.gguf
guidance_scale: 1.02
num_inference_steps: 20
cot: full
generated_at: 2026-09-28 14:30:00
source: local

# Score
X:1
T:Song Title
M:4/4
...
```

With `Style`, `Lyrics`, `Meta` (including seed + all inference params), and `Score` all in one file, any song can be 100% regenerated from its `info.md` alone.

---

## Installation

```bash
git clone https://github.com/<your-username>/song-generator.git
cd song-generator

python -m venv .venv
.\.venv\Scripts\activate        # Windows
source .venv/bin/activate        # Linux/macOS

pip install -r requirements.txt
```

**System requirements:**
- Python 3.10+
- FFmpeg installed and in `PATH` (verify with `ffmpeg -version`)
- (Local rendering) AMD GPU with Vulkan or NVIDIA GPU with CUDA + `audio.cpp`

---

## Configuration

Copy `.env.example` to `.env` and fill in:

```ini
# LLM Songwriting
AICREDITS_API_KEY=your_api_key
AICREDITS_BASE_URL=https://api.aicredits.in/v1
MODEL_NAME=google/gemini-3.8-flash
TEMPERATURE=0.75

# Local audio engine (optional)
LOCAL_SERVER_URL=http://127.0.0.1:8080

# Hugging Face Vault (cloud queue + storage)
HF_TOKEN=hf_your_write_token
HF_REPO=your_username/yue2-pipeline

# YouTube (optional)
YOUTUBE_CLIENT_SECRETS_FILE=client_secret.json
YOUTUBE_TOKEN_FILE=youtube_token.json
```

---

## Usage

All commands run through `main.py`.

### 1. Write songs

Generate song concepts and full lyrics.

```bash
python main.py write                        # 3 autonomous songs
python main.py write -n 5                   # 5 songs
python main.py write -t "rainy Tokyo synthwave"   # themed
python main.py write -m "anthropic/claude-3.5-sonnet"   # custom model
```

### 2. Render audio

Pick **one** of two routes:

**Local (GPU on your machine):**
```bash
# Start the audio.cpp server first, then:
python main.py local
python main.py local --seed 42              # reproducible batch
```

**Cloud (Kaggle GPU):**
```bash
python main.py dispatch                     # uploads queue to Hugging Face
python main.py dispatch --dry-run           # preview only
# → open yue2-music-generation.ipynb on Kaggle, run all cells
python main.py collect                      # downloads ZIP bundles back into songs/
```

### 3. Generate videos

Creates 1080p MP4 + PNG thumbnail from master WAV.

```bash
python main.py video                                        # all ready songs
python main.py video -s smelling-salts-for-the-ghost-orchid
python main.py video --keep-wav                             # keep the .wav after encode
python main.py video --force                                # re-render existing MP4s
```

### 4. Upload to YouTube

Titles and thumbnails are auto-converted to Title Case.

```bash
python main.py upload                        # all ready videos (public)
python main.py upload -p unlisted            # unlisted
python main.py upload -p private             # private
python main.py upload -s <slug> --force      # re-upload a specific song
python main.py upload --dry-run              # preview only
```

### 5. Utilities

```bash
python main.py status                        # local pipeline status table
python main.py status --remote               # + remote HF ledger
python main.py status -s <slug>              # single song
python main.py retry                         # re-queue all failed jobs
python main.py retry -s <slug>               # re-queue one song
python main.py clean                         # wipe remote outputs + reset queue
```

---

## Kaggle Setup (One-Time)

1. Add these to Kaggle **Secrets** (Add-ons → Secrets):
   - `HF_TOKEN` — write-scoped Hugging Face token
   - `HF_REPO` — e.g. `yourname/yue2-pipeline`
   - `GITHUB_REPO` — *(optional)* full clone URL, e.g. `https://github.com/yourname/song-generator.git`
2. Notebook Settings → **Internet** → **ON**.
3. Accelerator → **GPU T4 x2**.
4. Edit the `GITHUB_REPO` fallback in Cell 1 if you're not using a secret.
5. Run all 7 cells.

The notebook clones this repo from GitHub in Cell 1, then imports every stage from `notebook/stages/*.py`. Any `git push` to your repo is picked up on the next Kaggle run — no manual sync step.

**Notebook cells at a glance:**

| Cell | Stage | What it does |
|------|-------|--------------|
| 1 | `s01_setup` | Clone repo, GPU check, install deps, load secrets, download audio.cpp binary |
| 2 | `s02_model` | Download YuE2 GGUF weights, write server config JSONs |
| 3 | `s03_servers` | Launch `audiocpp_server` on 8080 (and 8081 if dual-GPU), wait for health |
| 4 | `s04_queue` | Fetch `queue/jobs.json` from HF, display table, populate pending jobs |
| 5 | `s05_generate` | Render `.wav` + `-score.abc` + `-meta.json` per job across GPU workers |
| 6 | `s06_bundle` | Render MP4 + PNG per track, bundle into `batch-*.zip`, atomic HF push |
| 7 | `s07_verify` | List remote ZIP bundles, shut down servers |

---

## YouTube API Setup (One-Time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project.
2. Enable **YouTube Data API v3**.
3. Configure OAuth Consent Screen (External, add your Google account as Test User).
4. Create **OAuth client ID** → **Desktop app**.
5. Download the JSON → rename to `client_secret.json` → place in project root.
6. Run `python main.py upload` — a browser opens for authentication once, then the token is cached in `youtube_token.json`.

---

## Command Cheat Sheet

```
python main.py write      [-n COUNT] [-t THEME] [-m MODEL]
python main.py local      [--seed N]
python main.py dispatch   [--seed N] [--dry-run]
python main.py collect
python main.py retry      [-s SLUG] [--dry-run]
python main.py status     [-s SLUG] [-r/--remote]
python main.py video      [-s SLUG] [--keep-wav] [--force]
python main.py upload     [-s SLUG] [-p unlisted|private|public] [--force] [--dry-run]
python main.py clean
```

---

## Batch Manifests

Each generation batch writes a manifest to `songs/.manifests/<batch_id>.json` containing per-song seed, timing, and RTF. Cloud batches ship their manifest inside the returned ZIP, and `collect` extracts it automatically.
