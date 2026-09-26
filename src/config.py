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
