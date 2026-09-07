import shutil
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, QThread, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import cuda_runtime, db, glossary, materials, term_stats
from app.auto_recorder import KST, AutoRecordController
from app.cancellation import ProcessingCancelled
from app.corrector import TranscriptCorrector
from app.paths import DATA_DIR, MATERIALS_DIR, RECORDINGS_DIR, SUMMARIES_DIR, TRANSCRIPTS_DIR
from app.recorder import Recorder
from app.schedule import load_schedule, save_schedule
from app.summarizer import Summarizer
from app.transcriber import Transcriber
from app.utils import hash_file
from app.word_review import FlaggedWord, find_ambiguous_words, generate_candidates, load_words, save_words

WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]
LECTURE_ID_ROLE = 1000
WORD_ROLE = 1001

# 앱 전체에 같은 색, 여백, 버튼 규칙을 적용합니다.
# 스타일을 한 곳에 모으면 화면을 수정할 때 여러 위젯을 찾아다니지 않아도 됩니다.
APP_STYLESHEET = """
QMainWindow {
    background: #F6F8FC;
    color: #172033;
}
QFrame#appHeader, QFrame#detailHeader, QFrame#statusBar, QWidget#sidebar, QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #E4E8F0;
    border-radius: 14px;
}
QFrame#appHeader { border: none; background: transparent; }
QWidget#sidebar { min-width: 290px; }
QLabel#appTitle { color: #152238; font-size: 25px; font-weight: 700; }
QLabel#appSubtitle, QLabel#sectionLabel, QLabel#lectureMeta, QLabel#recordHint {
    color: #65728A;
}
QLabel#sectionLabel { font-size: 12px; font-weight: 700; letter-spacing: 0.4px; }
QLabel#lectureTitle { color: #172033; font-size: 20px; font-weight: 700; }
QLabel#dialogHeadline { color: #172033; font-size: 14px; font-weight: 600; }
QLabel#infoNote {
    color: #4A5568;
    background: #F1F5FD;
    border: 1px solid #DCE6F8;
    border-radius: 10px;
    padding: 12px;
}
QLineEdit, QTextEdit, QTreeWidget {
    background: #FFFFFF;
    border: 1px solid #DDE3EE;
    border-radius: 9px;
    padding: 8px;
    selection-background-color: #DCE8FF;
    selection-color: #172033;
}
QLineEdit:focus, QTextEdit:focus, QTreeWidget:focus {
    border: 1px solid #4F7EF7;
}
QLineEdit { min-height: 30px; }
/* The row highlight is painted by LectureItemDelegate, not from here: a
   stylesheet ::item background also gets drawn across the tree's indent
   gutter, which left a stray coloured block to the left of each row.
   selection-background-color is cleared for the same reason (it is what the
   native style fills the gutter with), and ::branch is deliberately left
   alone -- styling it at all makes Qt drop its expand/collapse arrow. */
QTreeWidget { padding: 5px; outline: 0; border-color: #E8ECF4; selection-background-color: transparent; }
QTreeWidget::item { padding: 0px 6px; margin: 2px 0; }
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D8DFEB;
    border-radius: 9px;
    color: #34415A;
    font-weight: 600;
    min-height: 31px;
    padding: 3px 10px;
}
QPushButton:hover { background: #F2F5FA; border-color: #BAC6DA; }
QPushButton:pressed { background: #E7ECF5; }
QPushButton:disabled { background: #F4F6F9; color: #A0AABD; border-color: #E6EAF0; }
QPushButton[variant="primary"] { background: #376BEA; color: #FFFFFF; border: none; }
QPushButton[variant="primary"]:hover { background: #285DD9; }
/* Without this the rule above keeps disabled primary buttons a solid blue, so
   they look clickable when they aren't. */
QPushButton[variant="primary"]:disabled { background: #DCE3F3; color: #A0AABD; }
QPushButton[variant="danger"] { color: #C73B4B; border-color: #E7C3C8; }
QPushButton[variant="danger"]:hover { background: #FDF3F4; border-color: #D98F99; }
QPushButton#headerButton { background: #FFFFFF; padding: 3px 14px; }
QPushButton#headerButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: right center;
    right: 7px;
}
QPushButton#autoStatusButton {
    background: #F4F7FC;
    border: none;
    color: #65728A;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 10px;
    text-align: left;
}
QPushButton#autoStatusButton:hover { background: #E9EFFA; color: #285DD9; }
QPushButton#autoStatusButton[recording="true"] { background: #FDF0F1; color: #C73B4B; }
QTabBar::tab {
    background: transparent;
    border: none;
    color: #718099;
    font-weight: 600;
    padding: 11px 16px;
    margin-right: 4px;
}
QTabBar::tab:selected { color: #285DD9; border-bottom: 2px solid #376BEA; }
QProgressBar {
    background: #EAF0FA;
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk { background: #376BEA; border-radius: 4px; }
QSplitter::handle { background: transparent; width: 10px; }
QSplitter::handle:hover { background: #DDE7FB; }
"""

STATUS_LABELS = {
    "recorded": "녹음됨",
    "transcribed": "녹취 완료",
    "summarized": "요약 완료",
    "failed": "처리 실패",
}


def _correction_status_label(lecture: db.Lecture) -> str | None:
    """None means the transcript is corrected (or there's nothing to correct
    yet). Otherwise, a short suffix to show next to the status label,
    distinguishing two different reasons a transcript is still raw:

    - never attempted: this lecture predates the correction feature, so
      raw_transcript_path was never set at all -- easy to mistake for
      "already corrected" if we only checked for a stuck-in-progress marker.
    - stuck mid-way: correction was attempted (raw_transcript_path exists)
      but transcript_path still equals it, meaning it failed before
      overwriting the transcript with corrected text (e.g. API credit ran
      out) -- retry_lecture resumes from here instead of skipping to summary.
    """
    if not lecture.transcript_path:
        return None
    if not lecture.raw_transcript_path:
        return "교정 안 됨(구버전)"
    if lecture.transcript_path == lecture.raw_transcript_path:
        return "교정 전"
    return None


class LectureItemDelegate(QStyledItemDelegate):
    """Draws a lecture row as a title line with a dimmer date/state line under
    it. The default delegate renders both lines in one colour and size, which
    makes long lists hard to scan."""

    LINE_GAP = 3
    VERTICAL_PADDING = 7
    TITLE_COLOR = QColor("#172033")
    TITLE_COLOR_SELECTED = QColor("#1F55CB")
    META_COLOR = QColor("#8A94A6")
    META_COLOR_SELECTED = QColor("#5478C6")
    SELECTED_BG = QColor("#E6EEFF")
    HOVER_BG = QColor("#F2F5FA")

    def _paint_row_background(self, painter, opt):
        """Rounded highlight over the text cell only. Done here instead of in
        the stylesheet because a QSS ::item background is also painted across
        the indent gutter, which showed up as a detached block on the left."""
        if opt.state & QStyle.State_Selected:
            color = self.SELECTED_BG
        elif opt.state & QStyle.State_MouseOver:
            color = self.HOVER_BG
        else:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(QRectF(opt.rect).adjusted(0, 2, 0, -2), 8, 8)
        painter.restore()

    def _meta_font(self, base: QFont) -> QFont:
        meta = QFont(base)
        meta.setPointSizeF(max(base.pointSizeF() - 1.0, 7.5))
        return meta

    def _split(self, index) -> tuple[str, str]:
        text = str(index.data(Qt.DisplayRole) or "")
        title, _, meta = text.partition("\n")
        return title, meta

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()

        self._paint_row_background(painter, opt)

        # Month headers keep the plain single-line rendering, on top of the
        # highlight drawn above.
        if not index.parent().isValid():
            super().paint(painter, option, index)
            return

        # The two text lines are drawn by hand below.
        opt.text = ""

        title, meta = self._split(index)
        rect = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        selected = bool(opt.state & QStyle.State_Selected)

        title_font = QFont(opt.font)
        meta_font = self._meta_font(opt.font)
        title_fm = QFontMetrics(title_font)
        meta_fm = QFontMetrics(meta_font)

        # Centre the two-line block, so the row looks the same whether or not
        # the stylesheet's item padding made the rect taller than the text.
        block_height = title_fm.height() + self.LINE_GAP + meta_fm.height()
        top = rect.top() + max(0, (rect.height() - block_height) // 2)

        painter.save()
        painter.setFont(title_font)
        painter.setPen(self.TITLE_COLOR_SELECTED if selected else self.TITLE_COLOR)
        title_rect = QRect(rect.left(), top, rect.width(), title_fm.height())
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            title_fm.elidedText(title, Qt.ElideRight, title_rect.width()),
        )

        if meta:
            painter.setFont(meta_font)
            painter.setPen(self.META_COLOR_SELECTED if selected else self.META_COLOR)
            meta_rect = QRect(
                rect.left(),
                top + title_fm.height() + self.LINE_GAP,
                rect.width(),
                meta_fm.height(),
            )
            painter.drawText(
                meta_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                meta_fm.elidedText(meta, Qt.ElideRight, meta_rect.width()),
            )
        painter.restore()

    def sizeHint(self, option, index):
        if not index.parent().isValid():
            return super().sizeHint(option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title_height = QFontMetrics(opt.font).height()
        meta_height = QFontMetrics(self._meta_font(opt.font)).height()
        height = title_height + self.LINE_GAP + meta_height + self.VERTICAL_PADDING * 2
        return QSize(opt.rect.width(), height)


def _build_app_icon(recording: bool = False, size: int = 64) -> QIcon:
    """Draws the app/tray icon in code so packaging doesn't need an extra
    image asset. A red dot badge shows when auto-recording is active.

    `size` exists for tools/make_icon.py, which redraws it at each resolution
    the .ico needs -- scaling one 64px bitmap down to 16px smears the glyph."""
    scale = size / 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#376BEA")))
    painter.drawRoundedRect(QRectF(2 * scale, 2 * scale, 60 * scale, 60 * scale), 14 * scale, 14 * scale)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Malgun Gothic")
    font.setBold(True)
    # Pixel size (not points) so the glyph keeps its proportions no matter what
    # DPI the machine reports.
    font.setPixelSize(max(1, round(size * 0.54)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "강")
    if recording:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#E5484D")))
        painter.drawEllipse(QRectF(40 * scale, 40 * scale, 20 * scale, 20 * scale))
    painter.end()
    return QIcon(pixmap)


class CancellableWorker(QThread):
    """Shared stop handling for the two long-running jobs.

    Both spend minutes inside a single library call, so stopping works by
    raising out of the per-segment / per-chunk callbacks they already report
    progress through.
    """

    progress = Signal(str, int)  # stage label, percent
    finished_ok = Signal(int)  # lecture_id
    failed = Signal(int, str)  # lecture_id, message
    cancelled = Signal(int)  # lecture_id

    # Summaries stream in a character at a time; only redraw every so often.
    SUMMARY_REPORT_STEP = 200

    def __init__(self, lecture_id: int):
        super().__init__()
        self.lecture_id = lecture_id
        self._cancel_requested = False
        self._last_reported_chars = 0

    def cancel(self):
        self._cancel_requested = True

    def _stop_if_cancelled(self):
        if self._cancel_requested:
            raise ProcessingCancelled()

    def _summary_progress(self, label: str, base: int):
        """Builds the on_delta callback Summarizer calls per streamed chunk."""

        def report(chars: int):
            self._stop_if_cancelled()
            if chars - self._last_reported_chars < self.SUMMARY_REPORT_STEP:
                return
            self._last_reported_chars = chars
            # Real text length, not a guessed percentage, so a long summary
            # never looks stuck.
            self.progress.emit(f"{label} ({chars:,}자)", base + min(chars // 200, 28))

        return report


class ProcessingWorker(CancellableWorker):
    """Runs STT + summarization off the UI thread."""

    def __init__(self, lecture_id: int, audio_path: Path, title: str):
        super().__init__(lecture_id)
        self.audio_path = audio_path
        self.title = title

    def _stt_progress(self, fraction: float):
        self._stop_if_cancelled()
        self.progress.emit("음성 인식 중...", int(fraction * 50))

    def run(self):
        try:
            lecture = db.get_lecture(self.lecture_id)
            date_str = (lecture.recorded_at if lecture else datetime.now().isoformat())[:10].replace("-", "")
            file_stem = f"{date_str}_{self.lecture_id}"

            self.progress.emit("음성 인식 중...", 0)
            transcriber = Transcriber()
            self._stop_if_cancelled()
            result = transcriber.transcribe(
                self.audio_path, progress_cb=self._stt_progress, hotwords=glossary.hotwords_string()
            )
            TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            # Raw STT output + per-word confidence are kept for the "애매한 단어
            # 검토" feature -- the corrected transcript below is what's actually
            # shown/summarized.
            raw_transcript_path = TRANSCRIPTS_DIR / f"{file_stem}_raw.txt"
            raw_transcript_path.write_text(result.text, encoding="utf-8")
            words_path = TRANSCRIPTS_DIR / f"{file_stem}_words.json"
            save_words(words_path, result.words)
            # Recorded as the transcript right away (pointing at the raw text
            # for now) so that if correction/summary fails below, retrying
            # doesn't re-run STT -- retry_lecture only redoes STT when
            # transcript_path is entirely unset.
            db.update_transcript(self.lecture_id, str(raw_transcript_path), str(raw_transcript_path), str(words_path))

            self._stop_if_cancelled()
            self.progress.emit("녹취록 교정 중...", 50)
            material_text = materials.load_materials_text(lecture.material_path if lecture else None)
            corrector = TranscriptCorrector()
            corrected_text = corrector.correct(
                result.text,
                glossary_terms=glossary.load_glossary(),
                on_delta=self._summary_progress("녹취록 교정 중...", 50),
                material_text=material_text,
            )
            transcript_path = TRANSCRIPTS_DIR / f"{file_stem}.txt"
            transcript_path.write_text(corrected_text, encoding="utf-8")
            db.update_transcript(
                self.lecture_id, str(transcript_path), str(raw_transcript_path), str(words_path)
            )
            term_stats.collect_from_correction(self.lecture_id, result.text, corrected_text)

            self._stop_if_cancelled()
            self._last_reported_chars = 0  # _summary_progress's counter, reused for this 2nd stream
            self.progress.emit("요약 정리 중...", 78)
            summarizer = Summarizer()
            summary = summarizer.summarize(
                corrected_text,
                self.title,
                on_delta=self._summary_progress("요약 정리 중...", 78),
                material_text=material_text,
            )
            SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
            summary_path = SUMMARIES_DIR / f"{file_stem}.md"
            summary_path.write_text(summary, encoding="utf-8")
            db.update_summary(self.lecture_id, str(summary_path))

            self.progress.emit("완료", 100)
            self.finished_ok.emit(self.lecture_id)
        except ProcessingCancelled:
            # Not a failure: whatever finished before the stop (usually the
            # transcript) is already saved and stays usable.
            self.cancelled.emit(self.lecture_id)
        except Exception as exc:  # surface to UI instead of crashing the thread
            db.mark_failed(self.lecture_id)
            self.failed.emit(self.lecture_id, str(exc))


class SummaryWorker(CancellableWorker):
    """Re-runs just the summarization step against an existing transcript."""

    def __init__(self, lecture_id: int, transcript_path: Path, summary_path: Path, title: str):
        super().__init__(lecture_id)
        self.transcript_path = transcript_path
        self.summary_path = summary_path
        self.title = title

    def run(self):
        try:
            self.progress.emit("요약 다시 생성 중...", 20)
            transcript = self.transcript_path.read_text(encoding="utf-8")
            self._stop_if_cancelled()
            lecture = db.get_lecture(self.lecture_id)
            summarizer = Summarizer()
            summary = summarizer.summarize(
                transcript,
                self.title,
                on_delta=self._summary_progress("요약 다시 생성 중...", 20),
                material_text=materials.load_materials_text(lecture.material_path if lecture else None),
            )
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            self.summary_path.write_text(summary, encoding="utf-8")
            db.update_summary(self.lecture_id, str(self.summary_path))

            self.progress.emit("완료", 100)
            self.finished_ok.emit(self.lecture_id)
        except ProcessingCancelled:
            # The existing summary (if any) is untouched, so nothing to undo.
            self.cancelled.emit(self.lecture_id)
        except Exception as exc:
            db.mark_failed(self.lecture_id)
            self.failed.emit(self.lecture_id, str(exc))


class CorrectTranscriptWorker(CancellableWorker):
    """Runs just the correction pass against an already-existing transcript --
    no audio needed. For lectures processed before the correction step
    existed, or to re-run it after the glossary picked up new terms."""

    def __init__(self, lecture_id: int, transcript_path: Path, title: str):
        super().__init__(lecture_id)
        self.transcript_path = transcript_path
        self.title = title

    def run(self):
        try:
            lecture = db.get_lecture(self.lecture_id)
            existing_raw = (
                Path(lecture.raw_transcript_path)
                if lecture and lecture.raw_transcript_path and Path(lecture.raw_transcript_path).is_file()
                else None
            )

            if existing_raw is not None:
                # Already went through the normal pipeline before -- re-correct
                # from the true original STT output, not from a previous
                # correction, so repeated runs don't compound edits.
                raw_transcript_path = existing_raw
                source_text = raw_transcript_path.read_text(encoding="utf-8")
            else:
                # Pre-dates the correction feature: what's on disk now is the
                # only copy there is. Keep it as the reference "raw" version
                # before overwriting the transcript with the corrected text.
                source_text = self.transcript_path.read_text(encoding="utf-8")
                raw_transcript_path = self.transcript_path.with_name(
                    self.transcript_path.stem + "_raw" + self.transcript_path.suffix
                )
                if not raw_transcript_path.is_file():
                    raw_transcript_path.write_text(source_text, encoding="utf-8")

            self._stop_if_cancelled()
            self.progress.emit("녹취록 교정 중...", 10)
            corrector = TranscriptCorrector()
            corrected_text = corrector.correct(
                source_text,
                glossary_terms=glossary.load_glossary(),
                on_delta=self._summary_progress("녹취록 교정 중...", 10),
                material_text=materials.load_materials_text(lecture.material_path if lecture else None),
            )
            self.transcript_path.write_text(corrected_text, encoding="utf-8")
            term_stats.collect_from_correction(self.lecture_id, source_text, corrected_text)
            words_path = lecture.words_path if lecture else None
            db.update_transcript(self.lecture_id, str(self.transcript_path), str(raw_transcript_path), words_path)

            self.progress.emit("완료", 100)
            self.finished_ok.emit(self.lecture_id)
        except ProcessingCancelled:
            self.cancelled.emit(self.lecture_id)
        except Exception as exc:
            db.mark_failed(self.lecture_id)
            self.failed.emit(self.lecture_id, str(exc))


class RecordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("새 강의 녹음")
        self.setMinimumWidth(430)
        self.setStyleSheet(APP_STYLESHEET)

        self.recorder: Recorder | None = None
        self.elapsed_seconds = 0
        self.audio_path: Path | None = None
        self.is_paused = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(12)

        title_label = QLabel("새 강의 녹음")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        hint_label = QLabel("제목만 입력하고 녹음을 시작하세요. 완료 후 자동으로 녹취와 요약을 만듭니다.")
        hint_label.setObjectName("recordHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        field_label = QLabel("강의 제목")
        field_label.setObjectName("sectionLabel")
        layout.addWidget(field_label)
        self.title_edit = QLineEdit()
        self.title_edit.setText(f"{datetime.now():%Y-%m-%d} 강의")
        self.title_edit.selectAll()
        layout.addWidget(self.title_edit)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet("font-size: 32px; font-weight: 700; color: #172033; padding: 12px;")
        layout.addWidget(self.timer_label)

        btn_row = QHBoxLayout()
        self.record_btn = QPushButton("녹음 시작")
        self.record_btn.setProperty("variant", "primary")
        self.record_btn.clicked.connect(self.toggle_recording)
        btn_row.addWidget(self.record_btn)

        self.pause_btn = QPushButton("일시정지")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause)
        btn_row.addWidget(self.pause_btn)
        layout.addLayout(btn_row)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._tick)

    def toggle_recording(self):
        if self.recorder is None:
            self._start_recording()
        else:
            self._stop_recording()

    def toggle_pause(self):
        if self.recorder is None:
            return
        if self.is_paused:
            self.recorder.resume()
            self.ui_timer.start(1000)
            self.pause_btn.setText("일시정지")
            self.timer_label.setStyleSheet("font-size: 32px; font-weight: 700; color: #172033; padding: 12px;")
            self.is_paused = False
        else:
            self.recorder.pause()
            self.ui_timer.stop()
            self.pause_btn.setText("재개")
            self.timer_label.setStyleSheet("font-size: 32px; font-weight: 700; color: #7B879C; padding: 12px;")
            self.is_paused = True

    def _start_recording(self):
        title = self.title_edit.text().strip() or f"강의 {datetime.now():%Y-%m-%d %H:%M}"
        self.title_edit.setText(title)
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        self.audio_path = RECORDINGS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.wav"

        self.recorder = Recorder(self.audio_path)
        self.recorder.start()
        self.elapsed_seconds = 0
        self.ui_timer.start(1000)
        self.record_btn.setText("녹음 정지")
        self.pause_btn.setEnabled(True)
        self.title_edit.setEnabled(False)

    def _stop_recording(self):
        self.ui_timer.stop()
        self.pause_btn.setEnabled(False)
        self.recorder.stop()
        self.accept()

    def _tick(self):
        self.elapsed_seconds += 1
        self.recorder.drain()
        h, rem = divmod(self.elapsed_seconds, 3600)
        m, s = divmod(rem, 60)
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def result_title(self) -> str:
        return self.title_edit.text().strip()


class ScheduleDialog(QDialog):
    """8교시 시간표 기준 자동 녹음 켜기/끄기, 교시별 사용 여부, 오늘 쉬는 날 설정."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("자동 녹음 설정")
        self.setMinimumWidth(440)
        self.setStyleSheet(APP_STYLESHEET)

        self.schedule = load_schedule()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title_label = QLabel("자동 녹음 설정")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        hint_label = QLabel(
            "등록된 교시 시간이 되면 자동으로 녹음을 시작하고, 끝나면 자동으로 정리합니다. "
            "이 창을 닫아도 트레이 아이콘으로 계속 실행되니, 앱 자체는 켜둔 채로 두세요."
        )
        hint_label.setObjectName("recordHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        layout.addSpacing(4)
        self.master_check = QCheckBox("자동 녹음 사용")
        self.master_check.setChecked(self.schedule.auto_enabled)
        layout.addWidget(self.master_check)

        layout.addSpacing(6)
        period_label = QLabel("교시")
        period_label.setObjectName("sectionLabel")
        layout.addWidget(period_label)

        self.period_checks: dict[int, QCheckBox] = {}
        for p in self.schedule.periods:
            row = QCheckBox(f"{p.period}교시   {p.start} ~ {p.end}")
            row.setChecked(p.enabled)
            layout.addWidget(row)
            self.period_checks[p.period] = row

        layout.addSpacing(6)
        self.skip_today_check = QCheckBox("오늘은 쉬는 날 (오늘만 건너뛰기)")
        self.skip_today_check.setChecked(date.today().isoformat() in self.schedule.skip_dates)
        layout.addWidget(self.skip_today_check)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("저장")
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def save(self):
        self.schedule.auto_enabled = self.master_check.isChecked()
        for p in self.schedule.periods:
            p.enabled = self.period_checks[p.period].isChecked()

        today_str = date.today().isoformat()
        skip = {d for d in self.schedule.skip_dates if d >= today_str}  # drop stale past dates
        if self.skip_today_check.isChecked():
            skip.add(today_str)
        else:
            skip.discard(today_str)
        self.schedule.skip_dates = sorted(skip)

        save_schedule(self.schedule)


class GlossaryDialog(QDialog):
    """강의에서 자주 나오는 전문용어/영어 약어 목록. 음성 인식(hotwords)과 녹취록
    교정 단계 양쪽에 그대로 전달되어, 같은 용어가 반복해서 깨지는 걸 줄입니다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("용어집 관리")
        self.setMinimumSize(440, 480)
        self.setStyleSheet(APP_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title_label = QLabel("용어집 관리")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        hint_label = QLabel(
            "강의에서 자주 나오는 전문용어·영어 약어를 한 줄에 하나씩 등록하세요. "
            "음성 인식 정확도를 올리고, 녹취록 교정 시에도 참고합니다.\n"
            "예: Precision, Recall, AUC, ROC Curve, Confusion Matrix, predict_proba, scikit-learn"
        )
        hint_label.setObjectName("recordHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText("\n".join(glossary.load_glossary()))
        self.text_edit.setPlaceholderText("Precision\nRecall\nAUC\nConfusion Matrix\n...")
        layout.addWidget(self.text_edit, 1)

        # Terms the app added on its own (corrected in several lectures) are
        # named here so a wrong one is easy to spot and delete above.
        auto_terms = sorted(term_stats.auto_added_terms())
        if auto_terms:
            auto_label = QLabel(
                f"자동 등록된 용어 ({len(auto_terms)}개): " + ", ".join(auto_terms) + "\n"
                f"{term_stats.PROMOTE_AFTER_LECTURES}개 이상의 강의에서 반복해서 교정된 "
                "단어가 자동으로 등록됩니다. 잘못 등록된 게 있으면 위 목록에서 지우세요."
            )
            auto_label.setObjectName("recordHint")
            auto_label.setWordWrap(True)
            layout.addWidget(auto_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("저장")
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def save(self):
        terms = [line.strip() for line in self.text_edit.toPlainText().splitlines()]
        glossary.save_glossary([t for t in terms if t])


class TermReviewLoader(QThread):
    """Reads the raw STT word-confidence data and asks Claude for correction
    candidates -- both take a moment, so this runs off the UI thread."""

    loaded = Signal(list)  # list[FlaggedWord]
    failed = Signal(str)

    def __init__(self, lecture_id: int):
        super().__init__()
        self.lecture_id = lecture_id

    def run(self):
        try:
            lecture = db.get_lecture(self.lecture_id)
            if lecture is None or not lecture.words_path or not lecture.raw_transcript_path:
                self.loaded.emit([])
                return

            words = load_words(Path(lecture.words_path))
            raw_lines = Path(lecture.raw_transcript_path).read_text(encoding="utf-8").splitlines()
            flagged = find_ambiguous_words(words, raw_lines)
            generate_candidates(flagged, glossary.load_glossary())
            self.loaded.emit(flagged)
        except Exception as exc:
            self.failed.emit(str(exc))


class TermReviewDialog(QDialog):
    """음성 인식 신뢰도가 낮았던 단어를 모아 보여주고, 문맥과 후보를 참고해
    확정/직접 입력으로 교정합니다. 확정한 교정은 녹취록에 반영되고 용어집에도
    추가되어, 다음 강의부터 같은 단어의 인식 정확도가 올라갑니다."""

    def __init__(self, lecture_id: int, parent=None):
        super().__init__(parent)
        self.lecture_id = lecture_id
        self.flagged: list[FlaggedWord] = []
        self.current: FlaggedWord | None = None
        self.corrected_lines: list[str] = []
        self.raw_lines: list[str] = []
        self.resolved: set[str] = set()
        self.dirty = False

        self.setWindowTitle("애매한 단어 검토")
        self.setMinimumSize(780, 540)
        self.setStyleSheet(APP_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title_label = QLabel("애매한 단어 검토")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        self.status_label = QLabel("분석 중입니다...")
        self.status_label.setObjectName("recordHint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        body = QHBoxLayout()
        body.setSpacing(16)

        self.word_tree = QTreeWidget()
        self.word_tree.setHeaderHidden(True)
        self.word_tree.setMaximumWidth(260)
        self.word_tree.currentItemChanged.connect(self._on_word_selected)
        body.addWidget(self.word_tree)

        detail = QVBoxLayout()
        detail.setSpacing(8)

        self.sentence_label = QLabel("왼쪽 목록에서 단어를 선택하세요.")
        self.sentence_label.setWordWrap(True)
        self.sentence_label.setObjectName("recordHint")
        detail.addWidget(self.sentence_label)

        candidate_label = QLabel("후보")
        candidate_label.setObjectName("sectionLabel")
        detail.addWidget(candidate_label)
        self.candidate_row = QHBoxLayout()
        self.candidate_row.setSpacing(8)
        detail.addLayout(self.candidate_row)

        custom_row = QHBoxLayout()
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("후보에 없으면 직접 입력")
        custom_row.addWidget(self.custom_edit, 1)
        apply_custom_btn = QPushButton("이걸로 확정")
        apply_custom_btn.setProperty("variant", "primary")
        apply_custom_btn.clicked.connect(self._apply_custom)
        custom_row.addWidget(apply_custom_btn)
        detail.addLayout(custom_row)

        skip_btn = QPushButton("이 단어는 건너뛰기")
        skip_btn.clicked.connect(self._skip_current)
        detail.addWidget(skip_btn)

        detail.addStretch()
        body.addLayout(detail, 1)
        layout.addLayout(body, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        self.save_btn = QPushButton("저장하고 닫기")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_and_close)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

        self.loader = TermReviewLoader(lecture_id)
        self.loader.loaded.connect(self._on_loaded)
        self.loader.failed.connect(self._on_load_failed)
        self.loader.start()

    def _on_load_failed(self, message: str):
        self.status_label.setText(f"분석에 실패했습니다: {message}")

    def _on_loaded(self, flagged: list):
        lecture = db.get_lecture(self.lecture_id)
        if lecture is None or not lecture.transcript_path:
            self.status_label.setText("녹취록을 찾을 수 없습니다.")
            return
        self.corrected_lines = Path(lecture.transcript_path).read_text(encoding="utf-8").splitlines()

        if not flagged:
            self.status_label.setText(
                "검토할 만큼 애매한 단어가 없습니다 (또는 이 강의는 예전 버전으로 처리되어 "
                "분석 데이터가 없습니다)."
            )
            return

        self.flagged = flagged
        self.status_label.setText(f"신뢰도가 낮았던 단어 {len(flagged)}개를 찾았습니다. 하나씩 확인해보세요.")

        for f in self.flagged:
            item = QTreeWidgetItem([f"{f.word}  ({f.count}회)"])
            item.setData(0, WORD_ROLE, f.word)
            self.word_tree.addTopLevelItem(item)

        if self.word_tree.topLevelItemCount():
            self.word_tree.setCurrentItem(self.word_tree.topLevelItem(0))

    def _find_flagged(self, word: str) -> FlaggedWord | None:
        return next((f for f in self.flagged if f.word == word), None)

    def _on_word_selected(self, current: QTreeWidgetItem, _previous):
        self._clear_candidates()
        if current is None:
            self.current = None
            return
        word = current.data(0, WORD_ROLE)
        self.current = self._find_flagged(word)
        if self.current is None:
            return

        lines = []
        for occ in self.current.occurrences:
            corrected = (
                self.corrected_lines[occ.segment_index]
                if occ.segment_index < len(self.corrected_lines)
                else occ.sentence
            )
            lines.append(f"음성인식 원문: {occ.sentence}")
            lines.append(f"현재 녹취록: {corrected}")
            lines.append("")
        resolved_note = " (처리됨)" if self.current.word in self.resolved else ""
        self.sentence_label.setText(f"'{self.current.word}'{resolved_note}\n\n" + "\n".join(lines).strip())

        for candidate in self.current.candidates:
            btn = QPushButton(candidate)
            btn.clicked.connect(lambda _checked, c=candidate: self._apply(c))
            self.candidate_row.addWidget(btn)

    def _clear_candidates(self):
        while self.candidate_row.count():
            item = self.candidate_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.custom_edit.clear()

    def _apply_custom(self):
        text = self.custom_edit.text().strip()
        if text:
            self._apply(text)

    def _apply(self, replacement: str):
        if self.current is None:
            return
        for occ in self.current.occurrences:
            if occ.segment_index >= len(self.corrected_lines):
                continue
            line = self.corrected_lines[occ.segment_index]
            if self.current.word in line:
                self.corrected_lines[occ.segment_index] = line.replace(self.current.word, replacement)

        glossary.add_terms([replacement])
        self.resolved.add(self.current.word)
        self.dirty = True
        self.save_btn.setEnabled(True)
        self._move_to_next_unresolved()

    def _skip_current(self):
        if self.current is not None:
            self.resolved.add(self.current.word)
        self._move_to_next_unresolved()

    def _move_to_next_unresolved(self):
        current_index = self.word_tree.indexOfTopLevelItem(self.word_tree.currentItem())
        for i in range(current_index + 1, self.word_tree.topLevelItemCount()):
            item = self.word_tree.topLevelItem(i)
            if item.data(0, WORD_ROLE) not in self.resolved:
                self.word_tree.setCurrentItem(item)
                return
        self.sentence_label.setText("남은 단어를 모두 확인했습니다. '저장하고 닫기'를 눌러 반영하세요.")
        self._clear_candidates()

    def _save_and_close(self):
        lecture = db.get_lecture(self.lecture_id)
        if lecture and lecture.transcript_path:
            Path(lecture.transcript_path).write_text("\n".join(self.corrected_lines), encoding="utf-8")
            db.update_transcript_path(self.lecture_id, lecture.transcript_path)
        self.accept()


class AutoRecordStatusDialog(QDialog):
    """실시간 자동 녹음 상태 확인 + 제어(일시정지/다시 시작/지금 종료), 최근 실패 항목 재시도.
    모달로 띄우지 않아 열어둔 채로 다른 작업을 계속할 수 있습니다."""

    def __init__(self, controller: AutoRecordController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("자동 녹음 상태")
        self.setMinimumWidth(440)
        self.setStyleSheet(APP_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title_label = QLabel("자동 녹음 상태")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("recordHint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.pause_btn = QPushButton("일시정지")
        self.pause_btn.clicked.connect(self._toggle_pause)
        btn_row.addWidget(self.pause_btn)
        self.stop_btn = QPushButton("지금 종료")
        self.stop_btn.clicked.connect(self._stop_now)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        layout.addSpacing(10)
        material_header = QLabel("오늘 강의 자료")
        material_header.setObjectName("sectionLabel")
        layout.addWidget(material_header)

        self.material_label = QLabel("")
        self.material_label.setObjectName("recordHint")
        self.material_label.setWordWrap(True)
        layout.addWidget(self.material_label)

        material_row = QHBoxLayout()
        self.material_btn = QPushButton("자료 추가")
        self.material_btn.clicked.connect(self._pick_day_materials)
        material_row.addWidget(self.material_btn)
        self.material_clear_btn = QPushButton("전체 해제")
        self.material_clear_btn.clicked.connect(self._clear_day_materials)
        material_row.addWidget(self.material_clear_btn)
        material_row.addStretch()
        layout.addLayout(material_row)

        layout.addSpacing(10)
        failed_header = QLabel("최근 실패 항목")
        failed_header.setObjectName("sectionLabel")
        layout.addWidget(failed_header)

        self.failed_container = QVBoxLayout()
        self.failed_container.setSpacing(6)
        layout.addLayout(self.failed_container)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("닫기")
        close_btn.setProperty("variant", "primary")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start(1000)
        self._refresh()

    def _toggle_pause(self):
        if self.controller.is_paused:
            self.controller.resume_active()
        else:
            self.controller.pause_active()
        self._refresh()

    def _stop_now(self):
        self.controller.stop_now()
        self._refresh()

    def _today_iso(self) -> str:
        return datetime.now(KST).date().isoformat()

    def _pick_day_materials(self):
        today = self._today_iso()
        room = materials.MAX_MATERIALS - len(materials.get_day_materials(today))
        if room <= 0:
            QMessageBox.information(
                self,
                "자료 추가 불가",
                f"강의 자료는 최대 {materials.MAX_MATERIALS}개까지 등록할 수 있습니다.\n"
                "'전체 해제' 후 다시 등록해 주세요.",
            )
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"오늘 강의 자료 선택 ({room}개 더 추가 가능)",
            "",
            "강의 자료 (*.ipynb *.py *.md *.txt);;모든 파일 (*.*)",
        )
        if not file_paths:
            return

        try:
            materials.add_day_materials(today, [Path(p) for p in file_paths])
        except OSError as exc:
            QMessageBox.warning(self, "자료 등록 실패", str(exc))
            return

        if len(file_paths) > room:
            QMessageBox.information(
                self,
                "일부만 등록됨",
                f"최대 {materials.MAX_MATERIALS}개까지만 등록할 수 있어 앞의 {room}개만 추가했습니다.",
            )
        self._refresh_material_row()

    def _clear_day_materials(self):
        materials.clear_day_materials()
        self._refresh_material_row()

    def _refresh_material_row(self):
        stored = materials.get_day_materials(self._today_iso())
        if stored:
            names = ", ".join(Path(path).name for path in stored)
            self.material_label.setText(
                f"등록됨 ({len(stored)}/{materials.MAX_MATERIALS}개): {names}\n"
                "오늘 녹음되는 강의에 자동으로 첨부되어, 첫 교정·요약부터 반영됩니다."
            )
            self.material_clear_btn.setEnabled(True)
        else:
            self.material_label.setText(
                "오늘 수업의 강의안·실습 파일(.ipynb 등)을 미리 등록해두면, 이후 녹음되는 "
                f"강의에 자동으로 첨부되어 교정·요약 정확도가 올라갑니다. 최대 "
                f"{materials.MAX_MATERIALS}개까지 등록할 수 있습니다."
            )
            self.material_clear_btn.setEnabled(False)

    def _refresh(self):
        self._refresh_material_row()
        ctrl = self.controller
        recording = ctrl.active_period is not None

        if recording:
            elapsed = ""
            if ctrl.active_started_at:
                secs = max(0, int((datetime.now(KST) - ctrl.active_started_at).total_seconds()))
                elapsed = f" (경과 {secs // 60:02d}:{secs % 60:02d})"
            state = "일시정지됨" if ctrl.is_paused else "자동 녹음 중"
            self.status_label.setText(f"{ctrl.active_period}교시 {state}{elapsed}")
            self.pause_btn.setText("다시 시작" if ctrl.is_paused else "일시정지")
        else:
            next_p = ctrl.next_period()
            if next_p:
                self.status_label.setText(f"자동 녹음 대기 중 · 다음 교시: {next_p.period}교시 ({next_p.start} 시작)")
            elif load_schedule().auto_enabled:
                self.status_label.setText("오늘은 더 이상 예정된 교시가 없습니다.")
            else:
                self.status_label.setText("자동 녹음이 꺼져 있습니다.")
            self.pause_btn.setText("일시정지")

        self.pause_btn.setEnabled(recording)
        self.stop_btn.setEnabled(recording)

        self._refresh_failed_list()

    def _refresh_failed_list(self):
        while self.failed_container.count():
            item = self.failed_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        failed = [lec for lec in db.list_lectures() if lec.status == "failed"]
        if not failed:
            empty_label = QLabel("실패한 항목이 없습니다.")
            empty_label.setObjectName("recordHint")
            self.failed_container.addWidget(empty_label)
            return

        for lec in failed[:10]:
            row = QHBoxLayout()
            label = QLabel(lec.title)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            retry_btn = QPushButton("다시 시도")
            retry_btn.clicked.connect(lambda _checked, lid=lec.id: self._retry(lid))
            row.addWidget(retry_btn)
            row_widget = QWidget()
            row_widget.setLayout(row)
            self.failed_container.addWidget(row_widget)

    def _retry(self, lecture_id: int):
        main_window = self.parent()
        if main_window is not None:
            main_window.retry_lecture(lecture_id)
        self._refresh_failed_list()

    def closeEvent(self, event):
        self.refresh_timer.stop()
        super().closeEvent(event)


def _format_size(num_bytes: int) -> str:
    if num_bytes >= 1 << 30:
        return f"{num_bytes / (1 << 30):.1f}GB"
    return f"{num_bytes / (1 << 20):.0f}MB"


class CudaDownloadWorker(QThread):
    """Runs the CUDA runtime download off the UI thread -- it is well over 1GB."""

    progress = Signal(int, int)
    succeeded = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            cuda_runtime.install(
                progress_cb=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancel_requested,
            )
        except ProcessingCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit()


# 드라이버와 헷갈리기 쉬워서 창에 그대로 띄웁니다. 그래픽카드가 이미 잘 돌아가고
# 있는데 왜 1.3GB를 또 받아야 하는지 설명이 없으면 대부분 그냥 닫습니다.
DRIVER_NOTE = (
    "이 파일은 이미 설치된 그래픽 드라이버와 다른 것입니다.\n\n"
    "· 그래픽 드라이버 — 화면 출력처럼 그래픽카드를 쓰기 위한 기본 프로그램입니다. "
    "이미 설치되어 있고, 그래서 위에 카드 이름이 보입니다.\n\n"
    "· 지금 받는 파일 — 그 위에서 음성 인식 계산을 대신 처리하는 라이브러리"
    "(cuBLAS·cuDNN)입니다. 원래 CUDA Toolkit을 따로 설치해야 생기는 파일이라, "
    "드라이버만 있는 상태에서는 아직 없습니다.\n\n"
    "드라이버나 Windows 설정은 전혀 바꾸지 않습니다. 앱 전용 폴더에만 저장되고, "
    "필요 없어지면 이 창에서 삭제할 수 있습니다."
)

NO_GPU_NOTE = (
    "GPU 가속은 NVIDIA 그래픽카드가 있어야 쓸 수 있습니다. "
    "드라이버가 설치되어 있지 않은 경우에도 이렇게 표시될 수 있습니다.\n\n"
    "가속 없이도 녹음·녹취·요약 기능은 모두 그대로 동작합니다. "
    "텍스트로 바꾸는 데 시간이 더 걸릴 뿐입니다."
)


class GpuSetupDialog(QDialog):
    """GPU 가속(CUDA 런타임)을 내려받는 창입니다.

    큰 파일이라 실행 파일에 넣지 않고, GPU가 있는 컴퓨터에서 한 번만 받습니다.
    받지 않아도 앱은 CPU로 동작합니다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GPU 가속 설정")
        self.setMinimumWidth(520)
        self.setStyleSheet(APP_STYLESHEET)
        self.worker: CudaDownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title_label = QLabel("GPU 가속 설정")
        title_label.setObjectName("lectureTitle")
        layout.addWidget(title_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("dialogHeadline")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("recordHint")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        self.note_label = QLabel("")
        self.note_label.setObjectName("infoNote")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.remove_btn = QPushButton("삭제")
        self.remove_btn.clicked.connect(self._remove)
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch()
        self.close_btn = QPushButton("닫기")
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)
        self.action_btn = QPushButton("다운로드")
        self.action_btn.setProperty("variant", "primary")
        self.action_btn.clicked.connect(self._on_action)
        btn_row.addWidget(self.action_btn)
        layout.addLayout(btn_row)

        self._refresh()

    def _is_downloading(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    @staticmethod
    def _set_variant(button: QPushButton, variant: str):
        """Qt resolves property-based styles once, so a variant change only
        takes effect after the widget is re-polished."""
        button.setProperty("variant", variant)
        button.style().unpolish(button)
        button.style().polish(button)

    def _refresh(self):
        if self._is_downloading():
            return

        installed = cuda_runtime.is_installed()
        gpu = cuda_runtime.gpu_name()
        self.progress_bar.setVisible(False)
        self.note_label.setVisible(True)
        self.remove_btn.setVisible(installed)
        self.action_btn.setText("다시 다운로드" if installed else "다운로드")
        # Emphasise the download only while it is still the useful next click.
        # Once installed nothing needs emphasis, and the primary style would sit
        # left of "다시 다운로드" anyway, which reads as the wrong button.
        self._set_variant(self.action_btn, "" if installed else "primary")
        self._set_variant(self.close_btn, "")
        self.close_btn.setEnabled(True)

        if installed:
            self.status_label.setText(
                "GPU 가속이 설치되어 있습니다." if gpu is None else f"GPU 가속을 사용 중입니다. ({gpu})"
            )
            self.detail_label.setText(
                f"음성 인식에 GPU를 사용합니다. 저장 위치: {cuda_runtime.CUDA_DIR}"
            )
            self.note_label.setText(DRIVER_NOTE)
            self.action_btn.setVisible(True)
        elif not cuda_runtime.has_nvidia_gpu():
            self.status_label.setText("이 컴퓨터에서는 GPU 가속을 쓸 수 없습니다.")
            self.detail_label.setText("NVIDIA 그래픽카드를 찾지 못해 음성 인식은 CPU로 동작합니다.")
            self.note_label.setText(NO_GPU_NOTE)
            # Nothing to download, so the button would only be a dead control.
            self.action_btn.setVisible(False)
            self._set_variant(self.close_btn, "primary")
        else:
            self.status_label.setText(
                "GPU 가속을 쓸 수 있는 컴퓨터입니다."
                if gpu is None
                else f"GPU 가속을 쓸 수 있는 컴퓨터입니다. ({gpu})"
            )
            self.detail_label.setText(
                "약 1.3GB를 내려받으면 음성 인식이 크게 빨라집니다. 한 번만 받으면 되고, "
                "앱을 새 버전으로 바꿔도 다시 받지 않습니다. 지금 받지 않아도 앱은 CPU로 "
                "그대로 동작하며, 나중에 설정 메뉴에서 다시 열 수 있습니다."
            )
            self.note_label.setText(DRIVER_NOTE)
            self.action_btn.setVisible(True)

    def _on_action(self):
        if self._is_downloading():
            self.worker.cancel()
            self.action_btn.setEnabled(False)
            self.status_label.setText("중지하는 중입니다...")
            self.detail_label.setText("")
            return
        self._start_download()

    def _start_download(self):
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")
        self.status_label.setText("GPU 가속을 내려받는 중입니다.")
        self.detail_label.setText("연결하는 중입니다...")
        # Hidden while downloading so the progress bar isn't pushed off-screen
        # by the explanation the user has already read.
        self.note_label.setVisible(False)
        self.action_btn.setText("중지")
        self.action_btn.setVisible(True)
        self.action_btn.setEnabled(True)
        self._set_variant(self.action_btn, "danger")
        self.remove_btn.setVisible(False)
        self._set_variant(self.close_btn, "")
        self.close_btn.setEnabled(False)

        self.worker = CudaDownloadWorker(self)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _on_progress(self, done: int, total: int):
        if total <= 0:
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat("%p%")
        self.detail_label.setText(
            f"{_format_size(done)} / {_format_size(total)} · 창을 닫지 말고 기다려 주세요."
        )

    def _finish_download(self):
        self.worker = None
        self.close_btn.setEnabled(True)
        self.action_btn.setEnabled(True)

    def _on_succeeded(self):
        self._finish_download()
        self._refresh()
        QMessageBox.information(
            self,
            "GPU 가속 설치 완료",
            "GPU 가속을 설치했습니다. 앱을 다시 시작하면 적용됩니다.",
        )

    def _on_cancelled(self):
        self._finish_download()
        self._refresh()

    def _on_failed(self, message: str):
        self._finish_download()
        self._refresh()
        QMessageBox.warning(
            self,
            "다운로드 실패",
            f"GPU 가속 파일을 받지 못했습니다.\n\n{message}\n\n"
            "인터넷 연결을 확인한 뒤 다시 시도해 주세요. 그동안에도 앱은 CPU로 동작합니다.",
        )

    def _remove(self):
        reply = QMessageBox.question(
            self,
            "삭제 확인",
            "내려받은 GPU 가속 파일을 삭제할까요? 녹취 변환은 CPU로 동작하게 됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cuda_runtime.uninstall()
        self._refresh()

    def closeEvent(self, event):
        # Letting the window go while the thread still writes into the staging
        # folder would leave a half-finished install behind.
        if self._is_downloading():
            self.worker.cancel()
            self.worker.wait(5000)
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("강의 노트")
        self.resize(1180, 740)
        self.setMinimumSize(900, 620)
        self.setStyleSheet(APP_STYLESHEET)
        self.worker: ProcessingWorker | SummaryWorker | None = None
        # 무거운 AI 작업은 하나씩 실행하고, 나머지는 이 목록에서 순서대로 기다립니다.
        self._processing_queue: list[ProcessingWorker | SummaryWorker] = []

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(16)

        # 상단에는 앱의 목적을, 본문에는 실제 작업 공간을 분리해 처음 보는 사람도
        # "새 강의 추가 → 결과 확인" 흐름을 바로 이해하도록 구성합니다.
        app_header = QFrame()
        app_header.setObjectName("appHeader")
        header_layout = QHBoxLayout(app_header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        app_title = QLabel("강의 노트")
        app_title.setObjectName("appTitle")
        title_layout.addWidget(app_title)
        app_subtitle = QLabel("녹음한 강의를 녹취하고, 핵심만 다시 꺼내볼 수 있는 개인 학습 노트")
        app_subtitle.setObjectName("appSubtitle")
        title_layout.addWidget(app_subtitle)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()

        # Occasional actions live behind one header menu instead of taking a
        # sidebar row each -- the lecture list gets that space instead.
        settings_btn = QPushButton("설정")
        settings_btn.setObjectName("headerButton")
        settings_btn.setToolTip("자동 녹음과 보관함 관리 기능입니다.")
        settings_menu = QMenu(self)
        settings_menu.addAction("자동 녹음 설정", self.open_schedule_settings)
        settings_menu.addAction("자동 녹음 상태", self.open_auto_status)
        settings_menu.addSeparator()
        settings_menu.addAction("용어집 관리", self.open_glossary)
        settings_menu.addAction("GPU 가속 설정", self.open_gpu_setup)
        settings_menu.addAction("중복된 강의 정리", self.cleanup_duplicates)
        settings_btn.setMenu(settings_menu)
        header_layout.addWidget(settings_btn)
        root_layout.addWidget(app_header)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 12)
        sidebar_layout.setSpacing(8)

        # The two things you actually start work with, side by side on one row.
        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        new_btn = QPushButton("＋ 녹음하기")
        new_btn.setProperty("variant", "primary")
        new_btn.setToolTip("마이크로 새 강의를 녹음합니다.")
        new_btn.clicked.connect(self.start_new_recording)
        action_row.addWidget(new_btn, 1)

        import_btn = QPushButton("파일 열기")
        import_btn.setToolTip("이미 녹음한 오디오 파일을 가져옵니다.")
        import_btn.clicked.connect(self.import_audio_file)
        action_row.addWidget(import_btn, 1)
        sidebar_layout.addLayout(action_row)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("제목·녹취록·요약 검색")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        sidebar_layout.addWidget(self.search_edit)

        self.library_label = QLabel("전체 강의")
        self.library_label.setObjectName("sectionLabel")
        sidebar_layout.addWidget(self.library_label)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search_filter)

        self.list_widget = QTreeWidget()
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setItemDelegate(LectureItemDelegate(self.list_widget))
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.currentItemChanged.connect(self.show_lecture)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_list_context_menu)
        self.list_widget.setToolTip("두 번 클릭하면 제목을 바꿀 수 있고, 오른쪽 클릭하면 추가 메뉴를 엽니다.")
        self._delete_shortcut = QShortcut(QKeySequence.Delete, self.list_widget)
        self._delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._delete_shortcut.activated.connect(self.delete_selected_lectures)
        sidebar_layout.addWidget(self.list_widget, 1)

        # Auto-recording is a background feature, so it reports from a quiet
        # footer line rather than a button competing with the list.
        self.auto_status_btn = QPushButton("자동 녹음 대기 중")
        self.auto_status_btn.setObjectName("autoStatusButton")
        self.auto_status_btn.setToolTip("지금 자동 녹음 상태를 보고 일시정지/종료할 수 있습니다.")
        self.auto_status_btn.clicked.connect(self.open_auto_status)
        sidebar_layout.addWidget(self.auto_status_btn)
        splitter.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        detail_header = QFrame()
        detail_header.setObjectName("detailHeader")
        detail_layout = QVBoxLayout(detail_header)
        detail_layout.setContentsMargins(20, 16, 20, 16)
        detail_layout.setSpacing(4)
        detail_eyebrow = QLabel("강의 내용")
        detail_eyebrow.setObjectName("sectionLabel")
        detail_layout.addWidget(detail_eyebrow)
        self.lecture_title_label = QLabel("강의를 선택하세요")
        self.lecture_title_label.setObjectName("lectureTitle")
        detail_layout.addWidget(self.lecture_title_label)
        self.lecture_meta_label = QLabel("왼쪽에서 강의를 고르면 요약과 전체 녹취록을 확인할 수 있습니다.")
        self.lecture_meta_label.setObjectName("lectureMeta")
        detail_layout.addWidget(self.lecture_meta_label)
        content_layout.addWidget(detail_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        # The bar is a thin 8px strip; the percentage would be drawn on top of
        # it, and the status line already spells the stage out.
        self.progress_bar.setTextVisible(False)

        self.tabs = QTabWidget()
        self.summary_view = QTextEdit(readOnly=True)
        self.transcript_view = QTextEdit(readOnly=True)
        self.summary_view.setPlaceholderText("요약이 준비되면 이곳에 표시됩니다.")
        self.transcript_view.setPlaceholderText("녹취록이 준비되면 이곳에 표시됩니다.")
        self.tabs.addTab(self.summary_view, "요약 노트")
        self.tabs.addTab(self.transcript_view, "전체 녹취록")
        content_layout.addWidget(self.tabs, 1)

        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        status_layout = QVBoxLayout(status_bar)
        status_layout.setContentsMargins(14, 10, 14, 10)
        status_layout.setSpacing(7)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.status_label = QLabel("준비됨 · 강의를 녹음하거나 파일을 불러와 시작하세요.")
        self.status_label.setObjectName("lectureMeta")
        status_row.addWidget(self.status_label, 1)
        self.cancel_btn = QPushButton("처리 중지")
        self.cancel_btn.setProperty("variant", "danger")
        self.cancel_btn.setToolTip("진행 중인 녹취·요약 작업을 중지합니다.")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        status_row.addWidget(self.cancel_btn)
        status_layout.addLayout(status_row)
        status_layout.addWidget(self.progress_bar)
        content_layout.addWidget(status_bar)

        splitter.addWidget(content)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([330, 820])

        self._really_quit = False
        self._status_dialog: AutoRecordStatusDialog | None = None
        self.setWindowIcon(_build_app_icon())
        self._setup_tray()

        self.auto_controller = AutoRecordController(self)
        self.auto_controller.period_started.connect(self._on_auto_period_started)
        self.auto_controller.period_stopped.connect(self._on_auto_period_stopped)
        self.auto_controller.status_changed.connect(self._on_auto_status_changed)
        # The controller ran its first check inside the constructor, before the
        # signal above was connected -- ask again so the footer and tray show
        # the real state instead of the placeholder text.
        self.auto_controller.check_now()

        # Self-heals rows where correction actually completed (a _raw.txt
        # backup exists on disk) but the DB link never got saved -- cheap
        # filename check, silent, no harm running it every launch.
        db.backfill_raw_transcript_links()

        self._refresh_list()

        # Deferred so the main window is painted before the offer appears on top
        # of it, rather than the dialog being the first thing on screen.
        QTimer.singleShot(0, self._maybe_offer_gpu_setup)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(_build_app_icon(), self)
        self.tray.setToolTip("강의 노트")
        self.tray.activated.connect(self._on_tray_activated)

        tray_menu = QMenu()
        tray_menu.addAction("열기", self.activate_window)
        tray_menu.addAction("자동 녹음 설정", self.open_schedule_settings)
        tray_menu.addAction("자동 녹음 상태", self.open_auto_status)
        tray_menu.addSeparator()
        tray_menu.addAction("종료", self.quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    def activate_window(self):
        """Bring the window back to the front, whether it was minimized or
        hidden in the tray. Also called when a second launch of the exe hands
        off to this already-running instance."""
        self.showNormal()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.activate_window()

    def closeEvent(self, event):
        """창을 닫아도 자동 녹음이 계속 돌아가도록, 종료 대신 트레이로 숨깁니다."""
        if self._really_quit or not self.tray.isVisible():
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "강의 노트",
            "자동 녹음은 계속 실행됩니다. 트레이 아이콘을 클릭하면 다시 열 수 있어요.",
            QSystemTrayIcon.Information,
            3000,
        )

    def quit_app(self):
        self._really_quit = True
        self.auto_controller.shutdown()
        self.tray.hide()
        QApplication.instance().quit()

    def open_schedule_settings(self):
        dialog = ScheduleDialog(self)
        if dialog.exec() == QDialog.Accepted:
            dialog.save()
            self.auto_controller.check_now()

    def open_glossary(self):
        dialog = GlossaryDialog(self)
        if dialog.exec() == QDialog.Accepted:
            dialog.save()

    def open_gpu_setup(self):
        GpuSetupDialog(self).exec()

    def _maybe_offer_gpu_setup(self):
        """Shows the GPU download offer once, on the first run of a machine that
        could use it. Without this the exe just quietly runs on CPU and nobody
        would think to look in the settings menu for the reason."""
        marker = DATA_DIR / ".gpu_prompt_shown"
        if marker.exists():
            return
        try:
            marker.write_text("", encoding="utf-8")
        except OSError:
            return
        if cuda_runtime.is_installed() or not cuda_runtime.has_nvidia_gpu():
            return
        self.open_gpu_setup()

    def open_auto_status(self):
        if self._status_dialog is not None and self._status_dialog.isVisible():
            self._status_dialog.raise_()
            self._status_dialog.activateWindow()
            return
        self._status_dialog = AutoRecordStatusDialog(self.auto_controller, self)
        self._status_dialog.show()

    def _on_auto_period_started(self, period: int):
        self.tray.showMessage("강의 노트", f"{period}교시 자동 녹음을 시작했습니다.", QSystemTrayIcon.Information, 3000)

    def _on_auto_period_stopped(self, period: int, audio_path: Path, title: str):
        # Hash it like imports do, so "중복 정리" can spot a period that ended
        # up recorded twice (e.g. the app restarted mid-period).
        try:
            content_hash = hash_file(audio_path)
        except OSError:
            content_hash = None
        lecture_id = db.create_lecture(title, str(audio_path), content_hash)
        self._link_day_material(lecture_id)
        self._refresh_list()
        self._process_lecture(lecture_id, audio_path, title)
        self.tray.showMessage(
            "강의 노트", f"{period}교시 녹음이 끝나 녹취/요약을 시작합니다.", QSystemTrayIcon.Information, 3000
        )

    def _on_auto_status_changed(self, status: str):
        self.tray.setToolTip(f"강의 노트 — {status}")
        self.tray.setIcon(_build_app_icon(recording=self.auto_controller.active_period is not None))
        recording = self.auto_controller.active_period is not None
        self.auto_status_btn.setText(("● " if recording else "") + status)
        self.auto_status_btn.setProperty("recording", "true" if recording else "false")
        # Qt only restyles on a property change if the widget is re-polished.
        self.auto_status_btn.style().unpolish(self.auto_status_btn)
        self.auto_status_btn.style().polish(self.auto_status_btn)

    def _refresh_list(self):
        self.list_widget.clear()

        month_groups: dict[str, list[tuple[datetime, db.Lecture]]] = {}
        total = 0
        for lecture in db.list_lectures():  # already sorted recorded_at DESC
            dt = datetime.fromisoformat(lecture.recorded_at)
            month_key = f"{dt.year}년 {dt.month}월"
            month_groups.setdefault(month_key, []).append((dt, lecture))
            total += 1
        self.library_label.setText(f"전체 강의  {total}")

        for i, (month_key, entries) in enumerate(month_groups.items()):
            group_item = QTreeWidgetItem([f"{month_key}  ({len(entries)})"])
            group_item.setFlags(Qt.ItemIsEnabled)  # header only, not selectable
            bold_font = group_item.font(0)
            bold_font.setBold(True)
            group_item.setFont(0, bold_font)
            self.list_widget.addTopLevelItem(group_item)
            group_item.setExpanded(i == 0)  # most recent month open by default

            for dt, lecture in entries:
                day_label = f"{dt.month:02d}.{dt.day:02d}({WEEKDAYS_KR[dt.weekday()]})"
                status_label = STATUS_LABELS.get(lecture.status, lecture.status)
                correction_note = _correction_status_label(lecture)
                if correction_note:
                    status_label += f" · {correction_note}"
                material_count = len(materials.decode_paths(lecture.material_path))
                if material_count:
                    status_label += f" · 자료 {material_count}개"
                # Title on its own line so long lecture names stay readable,
                # with date and state underneath.
                child = QTreeWidgetItem([f"{lecture.title}\n{day_label} · {status_label}"])
                child.setData(0, LECTURE_ID_ROLE, lecture.id)
                group_item.addChild(child)

    def _reset_detail_header(self):
        """선택 항목이 없을 때 오른쪽 안내 문구를 기본 상태로 되돌립니다."""
        self.lecture_title_label.setText("강의를 선택하세요")
        self.lecture_meta_label.setText("왼쪽에서 강의를 고르면 요약과 전체 녹취록을 확인할 수 있습니다.")

    def _read_note(self, path_str: str | None, waiting_message: str) -> str:
        """결과 파일이 아직 없거나 읽을 수 없을 때도 화면이 멈추지 않게 합니다."""
        if not path_str:
            return waiting_message

        try:
            return Path(path_str).read_text(encoding="utf-8")
        except OSError:
            return "파일을 읽을 수 없습니다. 파일 위치가 변경되었는지 확인해 주세요."

    def _on_search_text_changed(self, _text: str):
        self._search_timer.start(250)

    def _apply_search_filter(self):
        query = self.search_edit.text().strip().lower()
        if not query:
            self._refresh_list()
            return

        for i in range(self.list_widget.topLevelItemCount()):
            group_item = self.list_widget.topLevelItem(i)
            any_visible = False
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                match = query in child.text(0).lower()
                if not match:
                    lecture = db.get_lecture(child.data(0, LECTURE_ID_ROLE))
                    if lecture:
                        for path_str in (lecture.transcript_path, lecture.summary_path):
                            path = Path(path_str) if path_str else None
                            if not path or not path.is_file():
                                continue
                            try:
                                content = path.read_text(encoding="utf-8").lower()
                            except OSError:
                                continue
                            if query in content:
                                match = True
                                break
                child.setHidden(not match)
                any_visible = any_visible or match
            group_item.setHidden(not any_visible)
            if any_visible:
                group_item.setExpanded(True)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int):
        lecture_id = item.data(0, LECTURE_ID_ROLE)
        if lecture_id is not None:
            self.rename_lecture(lecture_id)

    def _ask_for_lecture_title(self, dialog_title: str, label: str, initial_title: str) -> str | None:
        """긴 강의 파일명도 한눈에 보이도록 넓은 제목 입력 창을 보여줍니다."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(dialog_title)
        dialog.setLabelText(label)
        dialog.setInputMode(QInputDialog.TextInput)
        dialog.setTextValue(initial_title)

        # 기본 창(약 500px)보다 약 두 배 넓게 만들어 긴 제목을 편하게 확인합니다.
        dialog.setMinimumWidth(900)
        dialog.resize(900, dialog.sizeHint().height())

        if dialog.exec() != QDialog.Accepted:
            return None
        return dialog.textValue().strip()

    def rename_lecture(self, lecture_id: int):
        lecture = db.get_lecture(lecture_id)
        if lecture is None:
            return
        new_title = self._ask_for_lecture_title("이름 변경", "새 제목을 입력하세요", lecture.title)
        if new_title is None:
            return
        if not new_title or new_title == lecture.title:
            return
        db.update_title(lecture_id, new_title)
        self._refresh_list()
        self._select_lecture(lecture_id)

    def regenerate_summary(self, lecture_id: int):
        lecture = db.get_lecture(lecture_id)
        if lecture is None:
            return
        if not lecture.transcript_path or not Path(lecture.transcript_path).is_file():
            QMessageBox.warning(self, "요약 재생성 불가", "먼저 녹취록이 있어야 요약을 다시 만들 수 있습니다.")
            return

        transcript_path = Path(lecture.transcript_path)
        summary_path = Path(lecture.summary_path) if lecture.summary_path else SUMMARIES_DIR / f"{transcript_path.stem}.md"
        self._enqueue_worker(SummaryWorker(lecture_id, transcript_path, summary_path, lecture.title))

    def correct_transcript(self, lecture_id: int):
        """녹음 파일 없이, 이미 있는 녹취록 텍스트만으로 교정을 실행합니다.
        (오디오가 필요한 건 STT뿐이고, 교정은 텍스트만으로 가능합니다.)"""
        error = self._queue_transcript_correction(lecture_id)
        if error:
            QMessageBox.warning(self, "교정 불가", error)

    def _queue_transcript_correction(self, lecture_id: int) -> str | None:
        """Returns None on success (queued), or a reason string if it
        couldn't be queued -- lets bulk callers collect failures instead of
        popping a warning dialog per lecture."""
        lecture = db.get_lecture(lecture_id)
        if lecture is None:
            return "강의를 찾을 수 없습니다."
        if not lecture.transcript_path or not Path(lecture.transcript_path).is_file():
            return "먼저 녹취록이 있어야 교정할 수 있습니다."

        transcript_path = Path(lecture.transcript_path)
        self._enqueue_worker(CorrectTranscriptWorker(lecture_id, transcript_path, lecture.title))
        if lecture.summary_path:
            # transcript_path is re-read at run() time by SummaryWorker, so by
            # the time this runs (after the correction above) it already has
            # the corrected text -- the existing summary won't go stale.
            summary_path = Path(lecture.summary_path)
            self._enqueue_worker(SummaryWorker(lecture_id, transcript_path, summary_path, lecture.title))
        return None

    def bulk_correct_transcripts(self, lecture_ids: list[int]):
        skipped: list[str] = []
        queued = 0
        for lecture_id in lecture_ids:
            error = self._queue_transcript_correction(lecture_id)
            if error:
                lecture = db.get_lecture(lecture_id)
                name = lecture.title if lecture else str(lecture_id)
                skipped.append(f"- {name}: {error}")
            else:
                queued += 1

        if queued:
            self.status_label.setText(f"{queued}개 강의를 교정 대기열에 추가했습니다.")
        if skipped:
            QMessageBox.information(
                self, "일부 건너뜀", f"다음 {len(skipped)}개는 교정할 수 없어 건너뛰었습니다:\n" + "\n".join(skipped)
            )

    def open_term_review(self, lecture_id: int):
        dialog = TermReviewDialog(lecture_id, self)
        dialog.exec()
        if dialog.dirty:
            self.show_lecture(self.list_widget.currentItem(), None)
            QMessageBox.information(
                self,
                "용어 검토 완료",
                "녹취록에 반영했습니다. 요약에도 반영하려면 '요약 다시 생성'을 눌러주세요.",
            )

    def _lecture_item_at(self, pos) -> QTreeWidgetItem | None:
        """Find the lecture row under the cursor.

        QTreeWidget's customContextMenuRequested position is viewport-relative
        (the event starts on the viewport, then the tree consumes it). itemAt()
        also expects viewport coordinates. Right-click does not select the row,
        so callers must not rely on selectedItems() alone.
        """
        item = self.list_widget.itemAt(pos)
        if item is None:
            return None
        if item.data(0, LECTURE_ID_ROLE) is None:
            return None
        return item

    def _selected_lecture_items(self, clicked: QTreeWidgetItem | None = None) -> list[QTreeWidgetItem]:
        selected = [
            item for item in self.list_widget.selectedItems()
            if item.data(0, LECTURE_ID_ROLE) is not None
        ]
        if clicked is not None:
            if clicked not in selected:
                self.list_widget.clearSelection()
                clicked.setSelected(True)
                self.list_widget.setCurrentItem(clicked)
                return [clicked]
            return selected

        if selected:
            return selected
        current = self.list_widget.currentItem()
        if current is not None and current.data(0, LECTURE_ID_ROLE) is not None:
            return [current]
        return []

    def _lecture_ids_from_items(self, items: list[QTreeWidgetItem]) -> list[int]:
        lecture_ids: list[int] = []
        for item in items:
            value = item.data(0, LECTURE_ID_ROLE)
            if value is None:
                continue
            lecture_ids.append(int(value))
        return lecture_ids

    def _show_list_context_menu(self, pos):
        clicked = self._lecture_item_at(pos)
        items = self._selected_lecture_items(clicked)
        if not items:
            return

        lecture_ids = self._lecture_ids_from_items(items)
        if not lecture_ids:
            return

        menu = QMenu(self.list_widget)
        if len(lecture_ids) == 1:
            lecture = db.get_lecture(lecture_ids[0])
            rename_action = menu.addAction("이름 변경")
            rename_action.setData("rename")
            if lecture and lecture.status == "failed":
                retry_action = menu.addAction("다시 시도")
                retry_action.setData("retry")
            else:
                regenerate_action = menu.addAction("요약 다시 생성")
                regenerate_action.setData("regenerate")
                correct_action = menu.addAction("녹취록 교정")
                correct_action.setData("correct_transcript")
            if lecture and lecture.words_path:
                review_action = menu.addAction("애매한 단어 검토")
                review_action.setData("review_terms")
            attached = materials.decode_paths(lecture.material_path if lecture else None)
            if len(attached) < materials.MAX_MATERIALS:
                attach_action = menu.addAction(
                    f"강의 자료 추가 ({len(attached)}/{materials.MAX_MATERIALS})"
                    if attached
                    else "강의 자료 첨부"
                )
                attach_action.setData("attach_material")
            if attached:
                detach_action = menu.addAction(f"강의 자료 제거 ({len(attached)}개)")
                detach_action.setData("detach_material")
            menu.addSeparator()
        else:
            # Multi-select: only actions that make sense applied to a batch.
            # Correction doesn't need audio and is cheap to queue up for many
            # lectures at once (e.g. everything still on "구버전").
            bulk_correct_action = menu.addAction(f"선택한 {len(lecture_ids)}개 녹취록 교정")
            bulk_correct_action.setData("bulk_correct_transcript")
            # One notebook usually covers a whole day, so attaching it to every
            # period of that day at once is the common case.
            bulk_attach_action = menu.addAction(f"선택한 {len(lecture_ids)}개에 강의 자료 첨부")
            bulk_attach_action.setData("bulk_attach_material")
            menu.addSeparator()
        delete_action = menu.addAction("삭제")
        delete_action.setData("delete")

        action = menu.exec(self.list_widget.viewport().mapToGlobal(pos))
        if action is None:
            return
        kind = action.data()
        if kind == "delete":
            self.delete_selected_lectures(lecture_ids)
        elif kind == "rename":
            self.rename_lecture(lecture_ids[0])
        elif kind == "regenerate":
            self.regenerate_summary(lecture_ids[0])
        elif kind == "correct_transcript":
            self.correct_transcript(lecture_ids[0])
        elif kind == "bulk_correct_transcript":
            self.bulk_correct_transcripts(lecture_ids)
        elif kind == "retry":
            self.retry_lecture(lecture_ids[0])
        elif kind == "review_terms":
            self.open_term_review(lecture_ids[0])
        elif kind in ("attach_material", "bulk_attach_material"):
            self.attach_material(lecture_ids)
        elif kind == "detach_material":
            self.detach_material(lecture_ids[0])

    def attach_material(self, lecture_ids: list[int]):
        """Links lecture handouts (usually the day's .ipynb files) to these
        lectures. They become reference context for correction and
        summarisation, which beats hand-collecting glossary terms during
        class. Files add to whatever is already attached, up to the cap."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"강의 자료 선택 (최대 {materials.MAX_MATERIALS}개)",
            "",
            "강의 자료 (*.ipynb *.py *.md *.txt);;모든 파일 (*.*)",
        )
        if not file_paths:
            return

        sources = [Path(p) for p in file_paths]
        skipped_full = 0
        for lecture_id in lecture_ids:
            lecture = db.get_lecture(lecture_id)
            existing = materials.decode_paths(lecture.material_path if lecture else None)
            room = materials.MAX_MATERIALS - len(existing)
            if room <= 0:
                skipped_full += 1
                continue

            for source in sources[:room]:
                try:
                    dest = materials.store_for_lecture(lecture_id, source)
                except OSError as exc:
                    QMessageBox.warning(self, "자료 첨부 실패", f"{source.name}: {exc}")
                    return
                if str(dest) not in existing:
                    existing.append(str(dest))
            db.update_material(lecture_id, materials.encode_paths(existing))

        self._refresh_list()
        names = ", ".join(source.name for source in sources)
        extra = f"\n\n이미 {materials.MAX_MATERIALS}개가 첨부된 {skipped_full}개 강의는 건너뛰었습니다." if skipped_full else ""
        QMessageBox.information(
            self,
            "강의 자료 첨부",
            f"'{names}'을(를) {len(lecture_ids) - skipped_full}개 강의에 첨부했습니다.\n\n"
            "이미 요약까지 끝난 강의라면 '녹취록 교정'을 다시 실행해야 자료가 반영됩니다."
            f"{extra}",
        )

    def _link_day_material(self, lecture_id: int):
        """Attaches the handouts registered for today, if any, at the moment
        the lecture row is created -- so its first correction and summary
        already use them instead of needing a second pass."""
        stored = materials.get_day_materials(datetime.now(KST).date().isoformat())
        if stored:
            db.update_material(lecture_id, materials.encode_paths(stored))

    def detach_material(self, lecture_id: int):
        lecture = db.get_lecture(lecture_id)
        if lecture is None or not lecture.material_path:
            return

        attached = materials.decode_paths(lecture.material_path)
        db.update_material(lecture_id, None)

        # Only our own copies under materials/ are removed -- never the files
        # the user picked from their own folders -- and never one another
        # lecture still points at (a day's handout is shared by its periods).
        still_used: set[str] = set()
        for other in db.list_lectures():
            if other.id != lecture_id:
                still_used.update(materials.decode_paths(other.material_path))

        for path_str in attached:
            stored = Path(path_str)
            if stored.is_file() and stored.parent == MATERIALS_DIR and path_str not in still_used:
                try:
                    stored.unlink()
                except OSError:
                    pass
        self._refresh_list()

    def delete_selected_lectures(self, lecture_ids: list[int] | None = None):
        if lecture_ids is None:
            lecture_ids = self._lecture_ids_from_items(self._selected_lecture_items())
        if not lecture_ids:
            return

        lectures = [db.get_lecture(lecture_id) for lecture_id in lecture_ids]
        lectures = [lecture for lecture in lectures if lecture is not None]
        if not lectures:
            return

        if len(lectures) == 1:
            question = f"'{lectures[0].title}'을(를) 삭제할까요? 녹음/녹취록/요약 파일도 함께 삭제됩니다."
        else:
            question = f"선택한 {len(lectures)}개 강의를 삭제할까요? 녹음/녹취록/요약 파일도 함께 삭제됩니다."

        reply = QMessageBox.question(
            self,
            "삭제 확인",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Stop any queued/running job for these lectures first, so nothing
        # keeps writing transcript or summary files for a row that's gone (and
        # so the audio file isn't still held open when we try to delete it).
        self._cancel_jobs_for({lecture.id for lecture in lectures})

        undeleted: list[str] = []
        for lecture in lectures:
            undeleted += db.delete_lecture(lecture.id)
        self._refresh_list()
        self.summary_view.clear()
        self.transcript_view.clear()
        self._reset_detail_header()

        if undeleted:
            files = "\n".join(f"- {Path(path).name}" for path in undeleted)
            QMessageBox.information(
                self,
                "일부 파일 삭제 실패",
                "목록에서는 삭제했지만, 아래 파일은 다른 작업이 사용 중이라 지우지 못했습니다.\n"
                f"처리가 끝난 뒤 직접 삭제해 주세요.\n\n{files}",
            )

    def _cancel_jobs_for(self, lecture_ids: set[int]):
        """Drops queued jobs for these lectures and asks a running one to stop."""
        self._processing_queue = [
            worker for worker in self._processing_queue if worker.lecture_id not in lecture_ids
        ]
        if self.worker is not None and self.worker.isRunning() and self.worker.lecture_id in lecture_ids:
            self.worker.cancel()

    def cleanup_duplicates(self):
        db.backfill_content_hashes()
        groups = db.find_duplicate_groups()
        if not groups:
            QMessageBox.information(self, "중복 정리", "중복된 강의가 없습니다.")
            return

        total_to_delete = sum(len(group) - 1 for group in groups)
        preview = "\n".join(f"- {group[0].title} (중복 {len(group) - 1}개)" for group in groups)
        reply = QMessageBox.question(
            self,
            "중복 정리",
            f"{len(groups)}개 그룹에서 총 {total_to_delete}개의 중복 항목을 삭제합니다.\n"
            f"각 그룹에서 가장 진행이 많이 된 항목만 남깁니다.\n\n{preview}\n\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for group in groups:
            for lecture in group[1:]:  # group[0] is the keeper (sorted best-first)
                db.delete_lecture(lecture.id)

        self._refresh_list()
        QMessageBox.information(self, "중복 정리", f"{total_to_delete}개 항목을 삭제했습니다.")

    def start_new_recording(self):
        if self.auto_controller.active_period is not None:
            QMessageBox.warning(
                self, "녹음 불가", "지금 자동 녹음이 진행 중입니다. 마이크가 이미 사용 중이라 수동 녹음을 시작할 수 없어요."
            )
            return

        self.auto_controller.suspended = True  # don't let a scheduled period grab the mic mid-recording
        try:
            dialog = RecordDialog(self)
            if dialog.exec() == QDialog.Accepted and dialog.audio_path:
                title = dialog.result_title()
                lecture_id = db.create_lecture(title, str(dialog.audio_path))
                self._link_day_material(lecture_id)
                self._refresh_list()
                self._process_lecture(lecture_id, dialog.audio_path, title)
        finally:
            self.auto_controller.suspended = False

    def import_audio_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "녹음 파일 불러오기 (여러 개 선택 가능)",
            "",
            "오디오 파일 (*.wav *.mp3 *.m4a *.flac *.ogg *.aac);;모든 파일 (*)",
        )
        if not file_paths:
            return

        multiple = len(file_paths) > 1
        queued = 0
        duplicates: list[tuple[str, str]] = []
        errors: list[tuple[str, str]] = []

        for idx, file_path in enumerate(file_paths):
            src = Path(file_path)
            try:
                content_hash = hash_file(src)
            except OSError as exc:
                errors.append((src.name, str(exc)))
                continue

            existing = db.find_lecture_by_hash(content_hash)
            if existing is not None:
                duplicates.append((src.name, existing.title))
                continue

            if multiple:
                # Skip a per-file title prompt for batch imports -- use the filename
                # and let the user rename afterward (double-click any item to rename).
                title = src.stem
            else:
                default_title = src.stem
                entered = self._ask_for_lecture_title(
                    "강의 제목", "강의 제목을 입력하세요", default_title
                )
                if entered is None:
                    continue
                title = entered or default_title

            RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            dest = RECORDINGS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{idx}{src.suffix}"
            try:
                shutil.copy2(src, dest)
            except OSError as exc:
                errors.append((src.name, str(exc)))
                continue

            lecture_id = db.create_lecture(title, str(dest), content_hash)
            self._process_lecture(lecture_id, dest, title)
            queued += 1

        self._refresh_list()

        if duplicates:
            lines = "\n".join(f"- {name} (이미 '{title}'로 불러옴)" for name, title in duplicates)
            QMessageBox.information(self, "중복 건너뜀", f"다음 파일은 이미 불러온 적이 있어 건너뛰었습니다:\n{lines}")
        if errors:
            lines = "\n".join(f"- {name}: {msg}" for name, msg in errors)
            QMessageBox.critical(self, "불러오기 실패", lines)
        if queued > 1:
            self.status_label.setText(f"{queued}개 파일을 처리 대기열에 추가했습니다.")

    def _select_lecture(self, lecture_id: int):
        for i in range(self.list_widget.topLevelItemCount()):
            group_item = self.list_widget.topLevelItem(i)
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if child.data(0, LECTURE_ID_ROLE) == lecture_id:
                    group_item.setExpanded(True)
                    self.list_widget.setCurrentItem(child)
                    return

    def _process_lecture(self, lecture_id: int, audio_path: Path, title: str):
        self._enqueue_worker(ProcessingWorker(lecture_id, audio_path, title))

    def _enqueue_worker(self, worker: ProcessingWorker | SummaryWorker):
        """Only one Whisper/Claude job runs at a time -- the GPU (6GB VRAM) can't
        hold two large-v3 instances at once, so extra jobs (batch imports,
        summary regeneration) queue up and run one after another."""
        self._processing_queue.append(worker)
        if self.worker is None or not self.worker.isRunning():
            self._start_next_in_queue()

    def _start_next_in_queue(self):
        # finished_ok/failed/cancelled are emitted from inside the worker's
        # run(), so its QThread hasn't actually exited yet when we get here.
        # Rebinding self.worker below drops the last reference to it, and
        # destroying a still-running QThread aborts the whole process (the app
        # vanished with no error when a batch import started its next file).
        # The signal comes at the very end of run(), so this wait is instant.
        previous = self.worker
        if previous is not None and previous.isRunning():
            previous.wait()

        if not self._processing_queue:
            self._set_processing_ui(False)
            return
        self.worker = self._processing_queue.pop(0)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self._set_processing_ui(True)
        self.progress_bar.setValue(0)
        self.worker.start()

    def _set_processing_ui(self, running: bool):
        self.progress_bar.setVisible(running)
        self.cancel_btn.setVisible(running)
        self.cancel_btn.setEnabled(running)
        self.cancel_btn.setText("처리 중지")

    def cancel_processing(self):
        if self.worker is None or not self.worker.isRunning():
            return

        queued = len(self._processing_queue)
        extra = f"\n대기 중인 {queued}개 작업도 함께 취소됩니다." if queued else ""
        reply = QMessageBox.question(
            self,
            "처리 중지",
            "진행 중인 녹취·요약 작업을 중지할까요?\n"
            "이미 저장된 녹취록은 그대로 남고, 진행 중이던 단계는 저장되지 않습니다."
            f"{extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._processing_queue.clear()
        # The worker stops at its next progress callback, which can be a moment
        # away -- say so instead of leaving the button looking unresponsive.
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("중지하는 중...")
        self.status_label.setText("중지하는 중...")
        self.worker.cancel()

    def _on_progress(self, stage: str, percent: int):
        remaining = len(self._processing_queue)
        suffix = f" (대기 중 {remaining}개)" if remaining else ""
        self.status_label.setText(stage + suffix)
        self.progress_bar.setValue(percent)

    def _on_finished(self, lecture_id: int):
        self.status_label.setText("완료")
        self._set_processing_ui(False)
        self._refresh_list()
        self._start_next_in_queue()

    def _on_cancelled(self, lecture_id: int):
        self.status_label.setText("처리를 중지했습니다.")
        self._set_processing_ui(False)
        self._refresh_list()
        self._start_next_in_queue()

    def _on_failed(self, lecture_id: int, message: str):
        self._set_processing_ui(False)
        self.status_label.setText("오류 발생")
        self._refresh_list()

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("처리 실패")
        box.setText(message)
        retry_btn = box.addButton("다시 시도", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is retry_btn:
            self.retry_lecture(lecture_id)

        self._start_next_in_queue()

    def retry_lecture(self, lecture_id: int):
        """녹취록이 교정까지 끝나 있으면 요약만, 교정 전(원문) 상태면 교정부터,
        녹취록 자체가 없으면 원본 오디오부터 다시 처리합니다."""
        lecture = db.get_lecture(lecture_id)
        if lecture is None:
            return

        has_transcript = lecture.transcript_path and Path(lecture.transcript_path).is_file()
        stuck_at_raw = (
            has_transcript and lecture.raw_transcript_path and lecture.transcript_path == lecture.raw_transcript_path
        )
        if stuck_at_raw:
            # Failed during/after correction last time (e.g. API credit ran
            # out) -- transcript_path still points at the raw text, so
            # resuming with just a summary would summarize the uncorrected
            # version. Redo the correction step first.
            self.correct_transcript(lecture_id)
        elif has_transcript:
            self.regenerate_summary(lecture_id)
        elif lecture.audio_path and Path(lecture.audio_path).is_file():
            self._process_lecture(lecture_id, Path(lecture.audio_path), lecture.title)
        else:
            QMessageBox.warning(self, "다시 시도 불가", "원본 녹음 파일을 찾을 수 없습니다.")

    def show_lecture(self, current: QTreeWidgetItem, _previous):
        if current is None:
            return
        lecture_id = current.data(0, LECTURE_ID_ROLE)
        if lecture_id is None:  # month group header
            return
        lecture = db.get_lecture(lecture_id)
        if lecture is None:
            return

        recorded_at = datetime.fromisoformat(lecture.recorded_at)
        status_label = STATUS_LABELS.get(lecture.status, lecture.status)
        correction_note = _correction_status_label(lecture)
        if correction_note:
            status_label += f" · {correction_note} (원문 그대로)"
        self.lecture_title_label.setText(lecture.title)
        self.lecture_meta_label.setText(
            f"{recorded_at:%Y년 %m월 %d일 %H:%M} · {status_label}"
        )
        self.summary_view.setPlainText(
            self._read_note(lecture.summary_path, "아직 요약이 생성되지 않았습니다.")
        )
        self.transcript_view.setPlainText(
            self._read_note(lecture.transcript_path, "아직 녹취록이 생성되지 않았습니다.")
        )
