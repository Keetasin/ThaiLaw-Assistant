"""Central config. Retrieval constants below are Project2's tuned starting
values (see doc/PLAN.md §0.1) — this is a different corpus (Thai labor law,
not a student handbook), so TAU_ANSWER/TAU_REJECT/RRF weights must be
re-measured in Day 4 eval, not trusted as-is.
"""
import os

from dotenv import load_dotenv

load_dotenv()

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
DATA_DIR = os.path.join(ROOT, "data")

CHROMA_DIR = os.getenv("CHROMA_PERSIST_DIR", os.path.join(DATA_DIR, "chroma_db"))
BM25_PATH = os.path.join(DATA_DIR, "bm25.pkl")
CHUNKS_PATH = os.path.join(DATA_DIR, "chunks.jsonl")
SECTIONS_PATH = os.path.join(DATA_DIR, "sections.json")
TRACE_PATH = os.path.join(DATA_DIR, "traces.jsonl")

EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

# All HF models should live under a local cache once downloaded (Day 2) —
# same rationale as Project2/core/config.py: avoids drifting cache paths
# between scripts and skips redundant online lookups after first download.
os.environ.setdefault("HF_HOME", os.path.join(ROOT, ".hf_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "0")  # flip to "1" once models are cached locally

# --- LLM providers ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")

DOTBLUE_BASE_URL = os.getenv("DOTBLUE_BASE_URL", "https://ai.psu.blue/v1")
DOTBLUE_API_KEY = os.getenv("DOTBLUE_API_KEY", "")
DOTBLUE_MODEL = os.getenv("DOTBLUE_MODEL", "qwen/qwen3.6-flash")
DOTBLUE_JUDGE_MODEL = os.getenv("DOTBLUE_JUDGE_MODEL", "qwen/qwen3.6-plus")
DOTBLUE_FREE_MODEL = "PSU-LLM/psu-gemma"  # free tier (multiplier "ฟรี"), safe for smoke tests

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")

# --- Retrieval (Project2 starting values — retune Day 4, see doc/PLAN.md §3) ---
POOL = 10
FUSE_K = 6
RERANK_K = 5
RRF_C = 60
EXPAND_BUDGET_CHARS = 7000
TAU_ANSWER = 0.093
TAU_REJECT = 0.05

# --- Generation ---
NUM_CTX = 8192
NUM_PREDICT = 512
TEMPERATURE = 0.2

APP_PORT = int(os.getenv("APP_PORT", "5000"))
