import os
import shutil
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from dotenv import load_dotenv
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.paths import BASE_DIR, DATA_DIR, ENV_PATH, ensure_dirs
from app.single_instance import SingleInstance


def _load_env():
    """.env lives in DATA_DIR (survives exe rebuilds/reinstalls). Older
    installs kept it next to the exe -- migrate it over automatically
    instead of making the user redo their API key setup."""
    if not ENV_PATH.is_file():
        legacy_path = BASE_DIR / ".env"
        if legacy_path.is_file():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_path, ENV_PATH)
    load_dotenv(ENV_PATH)


def main():
    # A freshly copied exe distribution folder starts with none of the data
    # folders (models/recordings/transcripts/summaries) -- create them before
    # anything tries to write into them.
    ensure_dirs()
    _load_env()
    app = QApplication(sys.argv)

    instance = SingleInstance(app)
    if not instance.try_acquire():
        # Already running: that process raises its window, we just leave.
        return

    # Imported here, not at module scope, so a second launch exits without
    # paying for the faster-whisper/CUDA import chain.
    from app.ui.main_window import MainWindow

    # Windows 기본 한글 글꼴을 명시해, 버튼·목록·본문의 한글이 같은 느낌으로 보이게 합니다.
    app.setFont(QFont("Malgun Gothic", 10))
    # 운영체제마다 위젯 모양이 달라지는 문제를 줄여 앱의 화면을 일관되게 유지합니다.
    app.setStyle("Fusion")
    # 창을 닫아도(트레이로 숨김) 자동 녹음이 계속 돌아가도록 앱 자체는 종료되지 않게 합니다.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    instance.activate_requested.connect(window.activate_window)
    app.aboutToQuit.connect(instance.release)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
