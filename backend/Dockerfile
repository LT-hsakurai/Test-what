FROM python:3.11-slim

WORKDIR /app

# Install CPU-only PyTorch first (much smaller than CUDA version)
RUN pip install --no-cache-dir \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN grep -v "torch" requirements.txt | pip install --no-cache-dir -r /dev/stdin

COPY . .

EXPOSE ${PORT:-8000}
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
