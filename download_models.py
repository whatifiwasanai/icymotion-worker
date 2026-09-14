import os
import sys
import json
import time
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "/comfyui")
MANIFEST_PATH = os.path.join(COMFYUI_PATH, "models_manifest.json")

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

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

def download_file(s3_client, item):
    local_path = os.path.join(COMFYUI_PATH, item["local_path"])
    r2_key = item["r2_key"]
    
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        print(f"[models] Exists, skipping: {local_path}")
        return

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    print(f"[models] Downloading {r2_key} -> {local_path}...")
    start_time = time.time()
    s3_client.download_file(R2_BUCKET_NAME, r2_key, local_path)
    elapsed = time.time() - start_time
    print(f"[models] Downloaded {r2_key} in {elapsed:.2f}s")

def sync_models(max_workers=4):
    if not os.path.exists(MANIFEST_PATH):
        print(f"[models] Manifest file not found at {MANIFEST_PATH}")
        return

    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)

    files = manifest.get("files", [])
    s3_client = get_r2_client()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(download_file, s3_client, item) for item in files]
        for future in as_completed(futures):
            future.result()
