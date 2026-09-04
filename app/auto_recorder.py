from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app.paths import RECORDINGS_DIR
from app.recorder import Recorder
from app.schedule import Period, load_schedule

# Korea doesn't observe DST, so a fixed UTC+9 offset is always correct and
# needs no tzdata package (Windows Python ships no IANA tz database by
# default -- zoneinfo.ZoneInfo("Asia/Seoul") fails without it).
KST = timezone(timedelta(hours=9), name="KST")

CHECK_INTERVAL_MS = 15_000
DRAIN_INTERVAL_MS = 2_000


class AutoRecordController(QObject):
    """Watches the wall clock against the configured class schedule and
    starts/stops recording automatically -- no user interaction needed."""

    period_started = Signal(int)  # period number
    period_stopped = Signal(int, Path, str)  # period, audio_path, title
    status_changed = Signal(str)  # short human-readable status for the tray tooltip

    def __init__(self, parent=None):
        super().__init__(parent)
        self.recorder: Optional[Recorder] = None
        self.active_period: Optional[int] = None
        self.is_paused = False
        self.active_started_at: Optional[datetime] = None
        self._active_audio_path: Optional[Path] = None
        self._active_title: str = ""
        # Set by the UI while a manual recording is in progress, so a
        # scheduled period doesn't try to grab the mic at the same time.
        self.suspended = False
        # (date, period) pairs the user ended early. Without this the next
        # clock check sees we're still inside the period's time range and
        # immediately starts recording it again.
        self._finished_periods: set[tuple[str, int]] = set()

        self.drain_timer = QTimer(self)
        self.drain_timer.timeout.connect(self._drain)

        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self.check_now)
        self.check_timer.start(CHECK_INTERVAL_MS)

        self.check_now()

    def _now(self) -> datetime:
        return datetime.now(KST)

    def _finished_key(self, period: int, now: datetime) -> tuple[str, int]:
        return (now.date().isoformat(), period)

    def _current_period(self, schedule, now: datetime) -> Optional[Period]:
        if now.weekday() >= 5:  # Sat/Sun
            return None
        if now.date().isoformat() in schedule.skip_dates:
            return None

        now_t = now.time()
        for p in schedule.periods:
            if not p.enabled:
                continue
            start_t = time.fromisoformat(p.start)
            end_t = time.fromisoformat(p.end)
            if start_t <= now_t < end_t:
                return p
        return None

    def check_now(self):
        schedule = load_schedule()

        if not schedule.auto_enabled:
            if self.active_period is not None:
                self._stop_active()
            self.status_changed.emit("자동 녹음 꺼짐")
            return

        now = self._now()
        current = self._current_period(schedule, now)

        if current is None:
            if self.active_period is not None:
                self._stop_active()
            self.status_changed.emit("자동 녹음 대기 중")
            return

        if self._finished_key(current.period, now) in self._finished_periods:
            self.status_changed.emit(f"{current.period}교시 녹음 종료됨")
            return

        if self.suspended:
            # A manual recording owns the mic right now -- don't start a
            # competing stream. We simply miss this check; the next tick
            # will pick the period back up once the manual session ends.
            self.status_changed.emit("수동 녹음 중 (자동 녹음 대기)")
            return

        if self.active_period == current.period:
            return  # already recording this period, nothing to do

        if self.active_period is not None:
            # Shouldn't normally happen (periods don't overlap), but don't leave
            # a stale recording running if the schedule changed underneath us.
            self._stop_active()

        self._start_period(current, now)

    def _start_period(self, period: Period, now: datetime):
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        audio_path = RECORDINGS_DIR / f"auto_{now:%Y%m%d}_{period.period}.wav"

        self.recorder = Recorder(audio_path)
        self.recorder.start()
        self.active_period = period.period
        self.active_started_at = now
        self._active_audio_path = audio_path
        self._active_title = f"{now:%Y-%m-%d} {period.period}교시 (자동 녹음)"

        self.drain_timer.start(DRAIN_INTERVAL_MS)
        self.period_started.emit(period.period)
        self.status_changed.emit(f"{period.period}교시 자동 녹음 중")

    def _stop_active(self):
        self.drain_timer.stop()
        audio_path = self.recorder.stop()
        period = self.active_period
        title = self._active_title

        self.recorder = None
        self.active_period = None
        self.is_paused = False
        self.active_started_at = None
        self._active_audio_path = None
        self._active_title = ""

        self.period_stopped.emit(period, audio_path, title)

    def _drain(self):
        if self.recorder:
            self.recorder.drain()

    # -- manual controls for the currently-active auto-recorded period --

    def pause_active(self):
        if self.recorder is None or self.is_paused:
            return
        self.recorder.pause()
        self.drain_timer.stop()
        self.is_paused = True
        self.status_changed.emit(f"{self.active_period}교시 일시정지")

    def resume_active(self):
        if self.recorder is None or not self.is_paused:
            return
        self.recorder.resume()
        self.drain_timer.start(DRAIN_INTERVAL_MS)
        self.is_paused = False
        self.status_changed.emit(f"{self.active_period}교시 자동 녹음 중")

    def stop_now(self):
        """Manually end the active period early instead of waiting for its
        scheduled end time (e.g. class let out early). The period counts as
        done for the rest of the day, so it isn't picked back up while the
        clock is still inside its time range."""
        if self.active_period is None:
            return
        period = self.active_period
        self._finished_periods.add(self._finished_key(period, self._now()))
        self._stop_active()
        self.status_changed.emit(f"{period}교시 녹음 종료됨")

    def next_period(self) -> Optional[Period]:
        """The next period still to start today, if any -- for an idle-state
        status display ("다음 교시: 3교시 (11:00)")."""
        schedule = load_schedule()
        if not schedule.auto_enabled:
            return None
        now = self._now()
        if now.weekday() >= 5 or now.date().isoformat() in schedule.skip_dates:
            return None

        now_t = now.time()
        upcoming: Optional[Period] = None
        for p in schedule.periods:
            if not p.enabled:
                continue
            start_t = time.fromisoformat(p.start)
            if start_t > now_t and (upcoming is None or start_t < time.fromisoformat(upcoming.start)):
                upcoming = p
        return upcoming

    def shutdown(self):
        """Call on app quit so an in-progress auto-recording isn't lost."""
        if self.active_period is not None:
            self._stop_active()
        self.check_timer.stop()
        self.drain_timer.stop()
