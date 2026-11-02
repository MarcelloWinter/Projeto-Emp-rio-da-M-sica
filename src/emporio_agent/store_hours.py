"""Opening-hours logic (manual section 2)."""
from datetime import datetime, time, timedelta

from .config import TIMEZONE, now as clock

# weekday(): Monday=0 ... Sunday=6
HOURS = {
    **{d: (time(9, 0), time(18, 0)) for d in range(5)},
    5: (time(9, 0), time(13, 0)),
}
DAY_NAMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
             "sexta-feira", "sábado", "domingo"]


def store_status(now: datetime | None = None) -> dict:
    now = now.astimezone(TIMEZONE) if now else clock()
    hours = HOURS.get(now.weekday())
    is_open = bool(hours and hours[0] <= now.time() < hours[1])

    next_open = None
    if not is_open:
        probe = now
        for _ in range(8):
            h = HOURS.get(probe.weekday())
            if h:
                opening = probe.replace(hour=h[0].hour, minute=h[0].minute, second=0, microsecond=0)
                if opening > now:
                    next_open = opening
                    break
            probe = (probe + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "weekday": DAY_NAMES[now.weekday()],
        "is_open": is_open,
        "next_opening": (
            f"{DAY_NAMES[next_open.weekday()]}, {next_open.strftime('%d/%m')} às {next_open:%H:%M}"
            if next_open else None
        ),
        "regular_hours": "Segunda a sexta 09:00–18:00; sábado 09:00–13:00; domingo e feriados fechado",
        "note": "Feriados não são verificados automaticamente; confirme se a data for feriado nacional/local.",
    }
