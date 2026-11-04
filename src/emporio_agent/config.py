"""Central configuration: paths, environment variables and timezone."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)

DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
LOGS_DIR = ROOT / "logs"
POLICY_PDF = DATA_DIR / "politicas_da_loja.pdf"

TIMEZONE = ZoneInfo("America/Campo_Grande")

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


def stamp() -> str:
    """Real wall-clock time (ISO, microseconds, store timezone). Used to log when interactions actually happened;
    unlike now(), it ignores the AGENT_NOW demo clock."""
    from datetime import datetime

    return datetime.now(TIMEZONE).isoformat(timespec="microseconds")


def display_timezone():
    """Timezone used to *show* times. Default: the store's (America/Campo_Grande, UTC-4). Set DISPLAY_TZ to an IANA
    name (e.g. America/Sao_Paulo) or to "local" to use this computer's timezone. Stored timestamps keep their offset."""
    name = os.getenv("DISPLAY_TZ", "").strip()
    if not name:
        return TIMEZONE
    if name.lower() == "local":
        from datetime import datetime

        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(name)
    except Exception:
        return TIMEZONE


def format_when(iso: str) -> str:
    """'14:32' for today, '03/11 14:32' otherwise (in the display timezone)."""
    from datetime import datetime

    if not iso:
        return ""
    tz = display_timezone()
    moment = datetime.fromisoformat(iso).astimezone(tz)
    return moment.strftime("%H:%M") if moment.date() == datetime.now(tz).date() else moment.strftime("%d/%m %H:%M")
