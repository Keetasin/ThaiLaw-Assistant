# ตั้งค่า Environment และตัวแปรระบบ
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
DOTBLUE_BASE_URL = os.getenv("DOTBLUE_BASE_URL", "https://ai.psu.blue/v1")
DOTBLUE_API_KEY = os.getenv("DOTBLUE_API_KEY", "")
DOTBLUE_MODEL = os.getenv("DOTBLUE_MODEL", "qwen/qwen3.6-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))
NUM_PREDICT = int(os.getenv("NUM_PREDICT", "1200"))
NUM_CTX = int(os.getenv("NUM_CTX", "4096"))
APP_PORT = int(os.getenv("APP_PORT", "5000"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")
ROOT_DIR = Path(__file__).resolve().parents[1]
CHUNKS_PATH = os.getenv("CHUNKS_PATH", str(ROOT_DIR / "data" / "chunks.jsonl"))
CHROMA_DIR = os.getenv("CHROMA_DIR", str(ROOT_DIR / "data" / "index" / "chroma"))
BM25_PATH = os.getenv("BM25_PATH", str(ROOT_DIR / "data" / "index" / "bm25.pkl"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
POOL = int(os.getenv("RETRIEVAL_POOL", "20"))
RERANK_K = int(os.getenv("RERANK_K", "5"))
FUSE_K = int(os.getenv("FUSE_K", "10"))
RRF_C = int(os.getenv("RRF_C", "60"))
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cuda")
RERANK_DEVICE = os.getenv("RERANK_DEVICE", "cpu")
