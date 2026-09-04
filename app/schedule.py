import json
from dataclasses import asdict, dataclass, field

from app.paths import SCHEDULE_PATH

DEFAULT_PERIODS = [
    {"period": 1, "start": "09:00", "end": "09:55", "enabled": True},
    {"period": 2, "start": "10:00", "end": "10:55", "enabled": True},
    {"period": 3, "start": "11:00", "end": "11:55", "enabled": True},
    {"period": 4, "start": "12:00", "end": "12:55", "enabled": True},
    {"period": 5, "start": "14:00", "end": "14:55", "enabled": True},
    {"period": 6, "start": "15:00", "end": "15:55", "enabled": True},
    {"period": 7, "start": "16:00", "end": "16:55", "enabled": True},
    {"period": 8, "start": "17:00", "end": "17:55", "enabled": True},
]

# Periods used to end at :50. Existing installs already have that written to
# schedule.json, so changing the defaults alone would never reach them.
LEGACY_DEFAULT_ENDS = {
    1: "09:50",
    2: "10:50",
    3: "11:50",
    4: "12:50",
    5: "14:50",
    6: "15:50",
    7: "16:50",
    8: "17:50",
}


@dataclass
class Period:
    period: int
    start: str  # "HH:MM", 24h, Asia/Seoul
    end: str
    enabled: bool = True


@dataclass
class Schedule:
    auto_enabled: bool = False
    periods: list[Period] = field(default_factory=list)
    skip_dates: list[str] = field(default_factory=list)  # ISO dates ("2026-09-15"), e.g. holidays


def _upgrade_legacy_ends(periods: list[Period]) -> bool:
    """Move periods still sitting on the old :50 end time up to :55. Times the
    user edited themselves are left alone. Returns True if anything changed."""
    defaults = {p["period"]: p for p in DEFAULT_PERIODS}
    changed = False
    for period in periods:
        default = defaults.get(period.period)
        if default is None:
            continue
        if period.start == default["start"] and period.end == LEGACY_DEFAULT_ENDS.get(period.period):
            period.end = default["end"]
            changed = True
    return changed


def load_schedule() -> Schedule:
    if not SCHEDULE_PATH.is_file():
        default = Schedule(auto_enabled=False, periods=[Period(**p) for p in DEFAULT_PERIODS])
        save_schedule(default)
        return default

    try:
        raw = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Schedule(auto_enabled=False, periods=[Period(**p) for p in DEFAULT_PERIODS])

    periods = [Period(**p) for p in raw.get("periods", DEFAULT_PERIODS)]
    schedule = Schedule(
        auto_enabled=raw.get("auto_enabled", False),
        periods=periods,
        skip_dates=raw.get("skip_dates", []),
    )
    if _upgrade_legacy_ends(schedule.periods):
        save_schedule(schedule)
    return schedule


def save_schedule(schedule: Schedule) -> None:
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "auto_enabled": schedule.auto_enabled,
        "periods": [asdict(p) for p in schedule.periods],
        "skip_dates": schedule.skip_dates,
    }
    SCHEDULE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
