import sys
print(f"[debug] Executable: {sys.executable}", flush=True)
print(f"[debug] Version: {sys.version}", flush=True)

try:
    import requests
    print(f"[debug] requests OK: {requests.__version__}", flush=True)
except Exception as e:
    print(f"[debug] requests import failed: {repr(e)}", flush=True)

import os
import time
import json
import uuid
import boto3
import urllib.request
import urllib.parse
import websocket
import runpod
from download_models import sync_models

COMFYUI_PATH = os.environ.get("COMFYUI_PATH", "/comfyui")
COMFY_HOST = "127.0.0.1:8188"
WORKFLOW_FILE = os.path.join(COMFYUI_PATH, "workflow_api.json")

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

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
        region_name="auto",
    )

def upload_file_to_r2(local_path, r2_key):
    s3_client = get_r2_client()
    s3_client.upload_file(local_path, R2_BUCKET_NAME, r2_key)
    if R2_PUBLIC_URL:
        base = R2_PUBLIC_URL.rstrip("/")
        return f"{base}/{r2_key}"
    return f"https://{R2_BUCKET_NAME}.r2.cloudflarestorage.com/{r2_key}"

def download_input_file(url, filename):
    input_dir = os.path.join(COMFYUI_PATH, "input")
    os.makedirs(input_dir, exist_ok=True)
    local_path = os.path.join(input_dir, filename)
    print(f"[handler] Downloading input file from {url} to {local_path}")
    urllib.request.urlretrieve(url, local_path)
    return filename

def wait_for_comfyui():
    url = f"http://{COMFY_HOST}/system_stats"
    for i in range(60):
        try:
            req = urllib.request.urlopen(url)
            if req.getcode() == 200:
                print("[handler] ComfyUI is ready!")
                return True
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("ComfyUI server failed to start within timeout.")

def queue_prompt(prompt, client_id):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFY_HOST}/prompt", data=data, headers={"Content-Type": "application/json"})
    response = urllib.request.urlopen(req)
    return json.loads(response.read().decode("utf-8"))

def track_execution(prompt_id, client_id):
    ws = websocket.WebSocket()
    ws.connect(f"ws://{COMFY_HOST}/ws?clientId={client_id}")
    outputs = {}

    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "executing":
                if data.get("node") is None and data.get("prompt_id") == prompt_id:
                    break
            elif msg_type == "executed":
                if data.get("prompt_id") == prompt_id:
                    node_id = data.get("node")
                    outputs[node_id] = data.get("output", {})

    ws.close()
    return outputs

def process_workflow(prompt_data):
    client_id = str(uuid.uuid4())
    res = queue_prompt(prompt_data, client_id)
    prompt_id = res.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"Failed to queue prompt: {res}")

    print(f"[handler] Queued workflow prompt_id={prompt_id}")
    outputs = track_execution(prompt_id, client_id)
    return outputs

def handler(job):
    job_input = job.get("input", {})
    if not job_input:
        return {"error": "No input provided"}

    with open(WORKFLOW_FILE, "r") as f:
        workflow = json.load(f)

    if "video_url" in job_input:
        video_filename = f"input_video_{uuid.uuid4().hex[:8]}.mp4"
        download_input_file(job_input["video_url"], video_filename)
        if "47" in workflow:
            workflow["47"]["inputs"]["video"] = video_filename

    if "prompt" in job_input:
        if "6" in workflow:
            workflow["6"]["inputs"]["text"] = job_input["prompt"]

    if "negative_prompt" in job_input:
        if "7" in workflow:
            workflow["7"]["inputs"]["text"] = job_input["negative_prompt"]

    if "seed" in job_input:
        if "3" in workflow:
            workflow["3"]["inputs"]["seed"] = job_input["seed"]

    print("[handler] Executing ComfyUI workflow...")
    outputs = process_workflow(workflow)

    uploaded_urls = []
    output_dir = os.path.join(COMFYUI_PATH, "output")

    for node_id, output in outputs.items():
        if "gifs" in output:
            for item in output["gifs"]:
                filename = item.get("filename")
                subfolder = item.get("subfolder", "")
                file_path = os.path.join(output_dir, subfolder, filename)
                r2_key = f"outputs/{uuid.uuid4().hex}_{filename}"
                url = upload_file_to_r2(file_path, r2_key)
                uploaded_urls.append(url)
        if "images" in output:
            for item in output["images"]:
                filename = item.get("filename")
                subfolder = item.get("subfolder", "")
                file_path = os.path.join(output_dir, subfolder, filename)
                r2_key = f"outputs/{uuid.uuid4().hex}_{filename}"
                url = upload_file_to_r2(file_path, r2_key)
                uploaded_urls.append(url)

    return {"status": "success", "outputs": uploaded_urls}

def init_worker():
    print("[init] Syncing models from R2...")
    sync_models(max_workers=4)

    print("[init] Starting ComfyUI server in background...")
    import subprocess
    subprocess.Popen(
        ["python3.11", "main.py", "--listen", "127.0.0.1", "--port", "8188"],
        cwd=COMFYUI_PATH
    )

    wait_for_comfyui()

if __name__ == "__main__":
    init_worker()
    runpod.serverless.start({"handler": handler})
