"""
download_models.py

Checks each model file listed in models_manifest.json against local disk.
Anything missing is pulled from Cloudflare R2 (S3-compatible API) via boto3.
Safe to call on every cold start: files already present (e.g. on a warm
worker that already downloaded them) are skipped instantly.

Required environment variables:
  R2_ACCOUNT_ID          Cloudflare account ID (used to build the endpoint URL)
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_BUCKET_NAME
Optional:
  R2_ENDPOINT_URL         Overrides the auto-built endpoint if set
  COMFYUI_PATH            Defaults to /comfyui
"""

import os
import sys
import json
import time
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor, as_completed

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "/comfyui")
MANIFEST_PATH = os.path.join(COMFYUI_PATH, "models_manifest.json")

R2_ACCOUNT_ID = os.environ["R2_ACCOUNT_ID"]
R2_ACCESS_KEY_ID = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_ACCESS_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET_NAME = os.environ["R2_BUCKET_NAME"]
R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
)

# R2 has no multipart-download speedup like S3 Transfer Acceleration, but
# boto3's TransferConfig still parallelizes multipart GETs for large files.
from boto3.s3.transfer import TransferConfig

TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=64 * 1024 * 1024,   # 64MB
    multipart_chunksize=64 * 1024 * 1024,
    max_concurrency=8,
    use_threads=True,
)


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def download_one(s3, entry):
    local_path = os.path.join(COMFYUI_PATH, entry["local_path"])
    r2_key = entry["r2_key"]

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return f"SKIP (cached)  {entry['local_path']}"

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    tmp_path = local_path + ".part"

    t0 = time.time()
    s3.download_file(R2_BUCKET_NAME, r2_key, tmp_path, Config=TRANSFER_CONFIG)
    os.rename(tmp_path, local_path)
    dt = time.time() - t0
    size_gb = os.path.getsize(local_path) / (1024 ** 3)
    return f"DOWNLOADED     {entry['local_path']}  ({size_gb:.2f} GB in {dt:.1f}s)"


def sync_models(max_workers: int = 4):
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    entries = manifest["files"]
    s3 = get_client()

    print(f"[download_models] checking {len(entries)} model files against R2 bucket '{R2_BUCKET_NAME}'...")

    # Parallel downloads across DIFFERENT files (not within one file's
    # multipart chunks -- that's handled by TRANSFER_CONFIG separately).
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(download_one, s3, e): e for e in entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                print("[download_models]", future.result())
            except Exception as exc:
                print(f"[download_models] FAILED  {entry['local_path']}  ->  {exc}", file=sys.stderr)
                raise

    print("[download_models] all model files present.")


if __name__ == "__main__":
    sync_models()
