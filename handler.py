"""
handler.py -- RunPod Serverless worker for the Icymotion Wan2.1/ComfyUI pipeline.

Flow per request:
  1. (cold start only) sync models from R2, launch ComfyUI as a background process
  2. load the API-format workflow JSON (baked into the image OR passed in the request)
  3. patch a handful of node inputs (prompt text, reference image URL, driving video URL)
  4. submit to ComfyUI's /prompt endpoint, poll /history until done
  5. locate the output video file, upload it to R2, return the object's URL

Expected request payload:
{
  "input": {
    "prompt": "female, walking, cinematic lighting",   # optional override
    "reference_image_url": "https://.../ref.jpg",        # optional, downloaded and fed in
    "driving_video_url": "https://.../drive.mp4",         # optional, downloaded and fed in
    "overrides": {                                        # optional, raw node patches
      "47": {"text": "female, walking, cinematic lighting"}
    },
    "workflow": { ... }                                   # optional: full API-format JSON.
                                                            # if omitted, WORKFLOW_JSON_PATH is used.
  }
}
"""

import os
import io
import json
import time
import uuid
import requests
import runpod
import subprocess

from download_models import sync_models

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "/comfyui")
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

# Baked-in default workflow (API format). Export this from ComfyUI's
# "Export (API)" option on a pod that has every custom node installed --
# see the conversation this was generated from for why it must be that pod.
WORKFLOW_JSON_PATH = os.environ.get(
    "WORKFLOW_JSON_PATH", os.path.join(COMFYUI_PATH, "workflow_api.json")
)

# Known node IDs from the current workflow export -- CONFIRM these against
# your own exported API JSON, they can shift if the graph is edited.
NODE_ID_POSITIVE_PROMPT = "47"    # CLIPTextEncode (text="female ")
NODE_ID_REFERENCE_IMAGE = "81"    # LoadImage
NODE_ID_DRIVING_VIDEO = "2"       # VHS_LoadVideo

OUTPUT_DIR = os.path.join(COMFYUI_PATH, "output")
INPUT_DIR = os.path.join(COMFYUI_PATH, "input")

_comfy_process = None


# ---------------------------------------------------------------------------
# Cold start: models + ComfyUI server
# ---------------------------------------------------------------------------

def ensure_models():
    sync_models(max_workers=4)


def start_comfyui():
    global _comfy_process
    if _comfy_process is not None and _comfy_process.poll() is None:
        return  # already running

    print("[handler] launching ComfyUI...")
    _comfy_process = subprocess.Popen(
        [
            "python", "-u", "main.py",
            "--listen", COMFYUI_HOST,
            "--port", str(COMFYUI_PORT),
        ],
        cwd=COMFYUI_PATH,
    )

    # Wait for the server to come up
    for _ in range(180):  # up to ~3 minutes
        try:
            r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=2)
            if r.status_code == 200:
                print("[handler] ComfyUI is up.")
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)

    raise RuntimeError("ComfyUI failed to start within timeout")


def cold_start():
    ensure_models()
    start_comfyui()


# ---------------------------------------------------------------------------
# Request-time helpers
# ---------------------------------------------------------------------------

def download_to_input(url: str, filename: str) -> str:
    """Download a reference image / driving video from a URL into ComfyUI's input dir."""
    os.makedirs(INPUT_DIR, exist_ok=True)
    local_path = os.path.join(INPUT_DIR, filename)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    return filename  # ComfyUI LoadImage/VHS_LoadVideo take just the filename


def load_workflow(job_input: dict) -> dict:
    if "workflow" in job_input:
        return job_input["workflow"]
    with open(WORKFLOW_JSON_PATH) as f:
        return json.load(f)


def apply_overrides(workflow: dict, job_input: dict) -> dict:
    if "prompt" in job_input:
        workflow.setdefault(NODE_ID_POSITIVE_PROMPT, {}).setdefault("inputs", {})["text"] = job_input["prompt"]

    if "reference_image_url" in job_input:
        fname = download_to_input(job_input["reference_image_url"], f"ref_{uuid.uuid4().hex}.jpg")
        workflow.setdefault(NODE_ID_REFERENCE_IMAGE, {}).setdefault("inputs", {})["image"] = fname

    if "driving_video_url" in job_input:
        fname = download_to_input(job_input["driving_video_url"], f"drive_{uuid.uuid4().hex}.mp4")
        workflow.setdefault(NODE_ID_DRIVING_VIDEO, {}).setdefault("inputs", {})["video"] = fname

    # Raw escape hatch: {"overrides": {"<node_id>": {"<input_name>": <value>}}}
    for node_id, patch in job_input.get("overrides", {}).items():
        workflow.setdefault(node_id, {}).setdefault("inputs", {}).update(patch)

    return workflow


def submit_and_wait(workflow: dict, poll_interval: float = 2.0, timeout: int = 3600) -> dict:
    client_id = uuid.uuid4().hex
    resp = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=30,
    )
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    print(f"[handler] queued prompt_id={prompt_id}")

    start = time.time()
    while time.time() - start < timeout:
        h = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json()
        if prompt_id in h:
            status = h[prompt_id].get("status", {})
            if status.get("completed"):
                return h[prompt_id]
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {status}")
        time.sleep(poll_interval)

    raise TimeoutError(f"Prompt {prompt_id} did not finish within {timeout}s")


def find_output_video(history_entry: dict) -> str:
    """Walk the history's outputs for the first saved video file."""
    outputs = history_entry.get("outputs", {})
    for node_id, node_output in outputs.items():
        for key in ("gifs", "videos"):  # VHS_VideoCombine reports under 'gifs' in older builds
            for item in node_output.get(key, []):
                fname = item.get("filename")
                subfolder = item.get("subfolder", "")
                if fname and fname.lower().endswith((".mp4", ".webm")):
                    return os.path.join(OUTPUT_DIR, subfolder, fname)
    raise FileNotFoundError("No output video found in ComfyUI history for this prompt")


def upload_to_r2(local_path: str) -> str:
    import boto3
    from botocore.config import Config

    account_id = os.environ["R2_ACCOUNT_ID"]
    bucket = os.environ["R2_BUCKET_NAME"]
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("R2_ENDPOINT_URL", f"https://{account_id}.r2.cloudflarestorage.com"),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    key = f"outputs/{uuid.uuid4().hex}_{os.path.basename(local_path)}"
    s3.upload_file(local_path, bucket, key)

    public_base = os.environ.get("R2_PUBLIC_BASE_URL")  # e.g. your R2 public bucket domain / CDN
    if public_base:
        return f"{public_base.rstrip('/')}/{key}"
    return f"r2://{bucket}/{key}"  # caller resolves via their own R2 access if no public base configured


# ---------------------------------------------------------------------------
# RunPod entrypoint
# ---------------------------------------------------------------------------

def handler(event):
    job_input = event.get("input", {})

    workflow = load_workflow(job_input)
    workflow = apply_overrides(workflow, job_input)

    history_entry = submit_and_wait(workflow)
    video_path = find_output_video(history_entry)
    video_url = upload_to_r2(video_path)

    return {"video_url": video_url}


cold_start()
runpod.serverless.start({"handler": handler})
