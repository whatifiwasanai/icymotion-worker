import os
import sys
import json
import time
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "/comfyui")
MANIFEST_PATH = os.path.join(COMFYUI_PATH, "models_manifest.json")

# Safely fetch variables to prevent instant unlogged KeyError crashes
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

missing_env_vars = [
    var for var, val in [
        ("R2_ACCOUNT_ID", R2_ACCOUNT_ID),
        ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
        ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
        ("R2_BUCKET_NAME", R2_BUCKET_NAME),
    ] if not val
]

if missing_env_vars:
    print(f"[FATAL STARTUP ERROR] Missing required R2 environment variables: {missing_env_vars}", file=sys.stderr, flush=True)
    sys.exit(1)

R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
)
