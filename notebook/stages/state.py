"""Shared mutable state that flows between Kaggle notebook stages.

Every stage imports this module and reads/writes attributes on it.
Because it's a module-level singleton, all stages see the same values.
"""

# --- Secrets (populated in s01) ---
HF_TOKEN = None
HF_REPO = None

# --- Paths (populated in s01 / s02) ---
REPO_DIR = "/kaggle/working/_repo"
SHARED_DIR = None
BASE_DIR = "/kaggle/working/audiocpp"
MODEL_DIR = None

# --- Execution flags (populated in s01 / s03) ---
AVAILABLE_GPUS = 0
DUAL_GPU_MODE = False

# --- Queue / generation state (populated in s04 / s05) ---
QUEUE_DIR = "/kaggle/working/queue_in"
OUTPUT_DIR = "/kaggle/working/output"
jobs_path = None
jobs = []          # list of job dicts (mutated in place by s05)
pending_jobs = []  # subset of jobs where status == "pending"

# --- Live process handles (populated in s03, cleaned in s07) ---
server_processes = []  # list of (config, Popen, log_handle, log_path)