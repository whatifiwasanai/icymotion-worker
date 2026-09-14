FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    COMFYUI_PATH=/comfyui

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip git wget ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.11 /usr/bin/python

# ---- ComfyUI Core ----
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_PATH}
WORKDIR ${COMFYUI_PATH}
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt

# ---- Custom Nodes ----
WORKDIR ${COMFYUI_PATH}/custom_nodes

RUN git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-KJNodes/requirements.txt || true

RUN git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-Impact-Pack/requirements.txt || true

RUN git clone --depth 1 https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-Custom-Scripts/requirements.txt || true

RUN git clone --depth 1 https://github.com/yolain/ComfyUI-Easy-Use.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-Easy-Use/requirements.txt || true

RUN git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt || true

RUN git clone --depth 1 https://github.com/Kijai/ComfyUI-WanVideoWrapper.git \
    && python3.11 -m pip install --no-cache-dir -r ComfyUI-WanVideoWrapper/requirements.txt || true

# ---- RunPod & System Dependencies ----
WORKDIR ${COMFYUI_PATH}
RUN python3.11 -m pip install --no-cache-dir runpod boto3 botocore requests websocket-client

# ---- Copy Application Files ----
COPY handler.py ${COMFYUI_PATH}/handler.py
COPY download_models.py ${COMFYUI_PATH}/download_models.py
COPY models_manifest.json ${COMFYUI_PATH}/models_manifest.json
COPY workflow_api.json ${COMFYUI_PATH}/workflow_api.json

RUN mkdir -p models/diffusion_models models/text_encoders models/vae models/loras \
    models/clip_vision models/upscale_models models/checkpoints output input

CMD ["python3.11", "-u", "handler.py"]
