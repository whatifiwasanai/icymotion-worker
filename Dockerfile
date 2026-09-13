FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH=/comfyui

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3-pip python3.11-venv git wget ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# ---- ComfyUI core ----
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_PATH}
WORKDIR ${COMFYUI_PATH}
RUN pip install --no-cache-dir -r requirements.txt

# ---- Required custom node packs (verified list from workflow export) ----
WORKDIR ${COMFYUI_PATH}/custom_nodes

RUN git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git \
    && pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt || true

RUN git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack.git \
    && pip install --no-cache-dir -r ComfyUI-Impact-Pack/requirements.txt || true

RUN git clone --depth 1 https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git \
    && pip install --no-cache-dir -r ComfyUI-Custom-Scripts/requirements.txt || true

RUN git clone --depth 1 https://github.com/yolain/ComfyUI-Easy-Use.git \
    && pip install --no-cache-dir -r ComfyUI-Easy-Use/requirements.txt || true

RUN git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
    && pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt || true

# ---- RunPod worker deps ----
WORKDIR ${COMFYUI_PATH}
RUN pip install --no-cache-dir runpod boto3 requests websocket-client

# ---- Worker code ----
COPY handler.py ${COMFYUI_PATH}/handler.py
COPY download_models.py ${COMFYUI_PATH}/download_models.py
COPY models_manifest.json ${COMFYUI_PATH}/models_manifest.json

# Model dirs get populated at runtime from R2 (see download_models.py)
RUN mkdir -p models/diffusion_models models/text_encoders models/vae models/loras \
    models/clip_vision models/upscale_models models/checkpoints output input

CMD ["python", "-u", "handler.py"]
