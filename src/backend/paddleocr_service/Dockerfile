FROM python:3.11-slim

WORKDIR /app

# paddlex/opencv/paddle 在 slim 镜像里缺运行时图形库与 OpenMP，逐一补齐
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY app.py .

ENV PADDLE_PDX_CACHE_HOME=/models
VOLUME ["/models"]

EXPOSE 8900
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8900"]
