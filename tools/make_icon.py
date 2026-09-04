"""Renders assets/LectureNotes.ico from the same code that draws the tray icon.

The exe and the installer need a real .ico file, but the app draws its icon at
runtime -- a hand-made file would drift away from it. Regenerate after changing
_build_app_icon():

    .venv\\Scripts\\python tools\\make_icon.py

Pillow isn't a dependency of this project, so the container is written here. An
.ico is just a small header plus one blob per size, and Windows accepts PNG
blobs, which QPixmap can already produce.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ui.main_window import _build_app_icon  # noqa: E402

# Windows reaches for a different entry depending on context: the taskbar, the
# alt-tab switcher, explorer's view modes and the installer window all differ.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

OUTPUT = Path(__file__).resolve().parents[1] / "assets" / "LectureNotes.ico"

ICONDIR = "<HHH"  # reserved, type (1 = icon), image count
ICONDIRENTRY = "<BBBBHHII"  # w, h, colours, reserved, planes, bpp, size, offset


def _png_bytes(size: int) -> bytes:
    pixmap = _build_app_icon(size=size).pixmap(size, size)
    # QBuffer's own storage -- handing it a Python-owned QByteArray lets that
    # temporary be collected while Qt is still writing into it, which segfaults.
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not pixmap.save(buffer, "PNG"):
        raise SystemExit(f"could not encode the {size}px image")
    payload = bytes(buffer.data())
    buffer.close()
    return payload


def main() -> None:
    app = QApplication(sys.argv)

    images = [(size, _png_bytes(size)) for size in SIZES]

    offset = struct.calcsize(ICONDIR) + len(images) * struct.calcsize(ICONDIRENTRY)
    directory = b""
    for size, payload in images:
        directory += struct.pack(
            ICONDIRENTRY,
            0 if size >= 256 else size,  # 0 is how the format spells 256
            0 if size >= 256 else size,
            0,  # not a palette image
            0,
            1,
            32,
            len(payload),
            offset,
        )
        offset += len(payload)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "wb") as out:
        out.write(struct.pack(ICONDIR, 0, 1, len(images)))
        out.write(directory)
        for _, payload in images:
            out.write(payload)

    print(f"wrote {OUTPUT}")
    print(f"  {len(images)} sizes: {', '.join(str(s) for s, _ in images)}")
    print(f"  {OUTPUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
