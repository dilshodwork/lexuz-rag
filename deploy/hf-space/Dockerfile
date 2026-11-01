# Dalil - Hugging Face Spaces (Docker SDK, CPU basic: 2 vCPU, 16 GB RAM).
# Bu fayl Space repo'sining ildiziga ko'chiriladi (scripts/hf_deploy.py yig'adi); build konteksti = Space repo:
#   Dockerfile, README.md (Space YAML), start.sh, requirements-prod.txt, lexrag/, web/ (manba), eval/, report.md
#
# Qidiruv indeksi (ChromaDB + BM25, ~770 MB) image'ga KIRMAYDI: start'da HF_DATASET dan yuklanadi (lexrag/web/bootstrap.py).
# bge-m3 modeli (~2.2 GB) esa build vaqtida image'ga yoziladi - sababi README "Internetga chiqarish" bo'limida.

# ---------------------------------------------------------------- 1. frontend: web/ -> web/dist
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2. Python server
FROM python:3.13-slim

# HF Spaces konteynerni 1000-foydalanuvchi bilan ishga tushiradi
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DALIL_MODELS_DIR=/home/user/models \
    DALIL_MODEL_OFFLINE=1 \
    ANONYMIZED_TELEMETRY=False \
    HF_HUB_DISABLE_TELEMETRY=1 \
    ENV=production \
    TRUST_PROXY=1 \
    PORT=7860
WORKDIR /home/user/app

COPY requirements-prod.txt .
# sekin/uziladigan tarmoqda PyPI indeksi bo'sh qaytsa ("from versions: none") qayta urinadi
RUN pip install --retries 10 --timeout 120 -r requirements-prod.txt

# bge-m3 (fastembed / ONNX) - kod o'zgarsa ham qayta yuklanmasligi uchun alohida qatlam:
# faqat model yuklovchi fayllar ko'chiriladi (indexer.get_model - indeks qurishdagi aynan o'sha sozlama)
COPY --chown=user lexrag/__init__.py lexrag/config.py lexrag/indexer.py lexrag/
RUN mkdir -p /home/user/models && chown user /home/user/models
USER user
RUN DALIL_MODEL_OFFLINE=0 DALIL_DATA_DIR=/tmp/dalil-build python -c \
    "from lexrag.indexer import get_model; m = get_model('BAAI/bge-m3'); print('bge-m3:', len(next(iter(m.embed(['salom'])))))" \
    && rm -rf /tmp/dalil-build

COPY --chown=user lexrag/ lexrag/
COPY --chown=user eval/ eval/
COPY --chown=user report.md start.sh ./
COPY --from=web --chown=user /web/dist web/dist

EXPOSE 7860
CMD ["sh", "start.sh"]
