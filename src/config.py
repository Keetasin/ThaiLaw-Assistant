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
DOTBLUE_JUDGE_MODEL = os.getenv("DOTBLUE_JUDGE_MODEL", "qwen/qwen3.6-plus")
DOTBLUE_FREE_MODEL = "PSU-LLM/psu-gemma"
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
NUM_PREDICT = int(os.getenv("NUM_PREDICT", "512"))
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
APP_PORT = int(os.getenv("APP_PORT", "5000"))
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")
ROOT_DIR = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT_DIR / ".hf_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "0")
CHUNKS_PATH = os.getenv("CHUNKS_PATH", str(ROOT_DIR / "data" / "chunks.jsonl"))
CHROMA_DIR = os.getenv("CHROMA_DIR", os.getenv("CHROMA_PERSIST_DIR", str(ROOT_DIR / "data" / "index" / "chroma")))
BM25_PATH = os.getenv("BM25_PATH", str(ROOT_DIR / "data" / "index" / "bm25.pkl"))
SECTIONS_PATH = os.getenv("SECTIONS_PATH", str(ROOT_DIR / "data" / "sections.json"))
GRAPH_PATH = os.getenv("GRAPH_PATH", str(ROOT_DIR / "data" / "graph.json"))
TOPICS_PATH = os.getenv("TOPICS_PATH", str(ROOT_DIR / "data" / "curated" / "topic_agency_evidence_form_step.csv"))
TRACE_PATH = os.getenv("TRACE_PATH", str(ROOT_DIR / "data" / "traces.jsonl"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
POOL = int(os.getenv("RETRIEVAL_POOL", "10"))
RERANK_K = int(os.getenv("RERANK_K", "5"))
FUSE_K = int(os.getenv("FUSE_K", "6"))
RRF_C = int(os.getenv("RRF_C", "60"))
EXPAND_BUDGET_CHARS = int(os.getenv("EXPAND_BUDGET_CHARS", "7000"))
CONTEXT_BUDGET_CHARS = {
    "local": int(os.getenv("CONTEXT_BUDGET_LOCAL", "6000")),
    "api": int(os.getenv("CONTEXT_BUDGET_API", "12000")),
}
TAU_ANSWER = float(os.getenv("TAU_ANSWER", "0.093"))
TAU_REJECT = float(os.getenv("TAU_REJECT", "0.05"))
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cuda")
RERANK_DEVICE = os.getenv("RERANK_DEVICE", "cpu")
