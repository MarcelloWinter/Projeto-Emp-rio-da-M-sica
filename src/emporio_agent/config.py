"""Central configuration: paths, environment variables and timezone."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
LOGS_DIR = ROOT / "logs"
POLICY_PDF = DATA_DIR / "politicas_da_loja.pdf"

TIMEZONE = ZoneInfo("America/Campo_Grande")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

MAX_TOOL_ITERATIONS = 6
MAX_HISTORY_MESSAGES = 30


def now():
    """Current time in the store's timezone. AGENT_NOW (ISO, e.g. 2026-03-23T10:30) pins the
    clock, which is how the demo conversations line up with the dataset snapshot."""
    from datetime import datetime

    override = os.getenv("AGENT_NOW")
    if override:
        return datetime.fromisoformat(override).replace(tzinfo=TIMEZONE)
    return datetime.now(TIMEZONE)
