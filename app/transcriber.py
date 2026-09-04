import os
import sys
from pathlib import Path
from typing import Callable

from faster_whisper import WhisperModel

from app.paths import CUDA_DIR, MODEL_DIR

# RTX A3000 Laptop (6GB VRAM) handles large-v3 comfortably in float16.
DEFAULT_MODEL_SIZE = "large-v3"

# large-v3 on CPU is impractically slow for a full lecture, so machines with no
# usable NVIDIA GPU (missing driver, unsupported card, not enough VRAM, ...)
# fall back to this smaller model instead of just running large-v3 on CPU.
CPU_FALLBACK_MODEL_SIZE = "medium"


def _cuda_dll_dirs() -> list[Path]:
    """Where the cuBLAS/cuDNN DLLs might live, most specific first.

    The exe no longer bundles them (they were 1.9GB), so the usual location is
    the folder cuda_runtime.py downloads into. A development checkout still
    has them as pip packages inside the venv."""
    dirs: list[Path] = []
    if CUDA_DIR.is_dir():
        dirs.append(CUDA_DIR)

    try:
        import nvidia.cublas
        import nvidia.cudnn
    except ImportError:
        return dirs

    for pkg in (nvidia.cublas, nvidia.cudnn):
        # These are PEP 420 namespace packages (no __init__.py, __file__ is None) --
        # use __path__ to locate the install dir instead.
        for pkg_path in pkg.__path__:
            bin_dir = Path(pkg_path) / "bin"
            if bin_dir.is_dir():
                dirs.append(bin_dir)
    return dirs


def _register_cuda_dll_dirs() -> None:
    """faster-whisper (ctranslate2) loads cuBLAS/cuDNN lazily, on the first
    actual inference call, via a plain LoadLibrary that only honors the
    process PATH -- it does not respect os.add_dll_directory(). So do both
    here (add_dll_directory covers Python-level ctypes/import loads; PATH
    covers ctranslate2's own loader)."""
    if sys.platform != "win32":
        return

    for bin_dir in _cuda_dll_dirs():
        os.add_dll_directory(str(bin_dir))
        bin_dir_str = str(bin_dir)
        if bin_dir_str not in os.environ["PATH"]:
            os.environ["PATH"] = bin_dir_str + os.pathsep + os.environ["PATH"]


class Transcriber:
    def __init__(self, model_size: str = DEFAULT_MODEL_SIZE, device: str = "cuda", compute_type: str = "float16"):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _register_cuda_dll_dirs()
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=str(MODEL_DIR),
            )
        except Exception:
            if device != "cuda":
                raise
            # No usable NVIDIA GPU on this machine (no driver, unsupported card,
            # not enough VRAM for this model, ...). Different machines than the
            # one this was built on will hit this, not just the DLL-path issue
            # below -- fall back to CPU instead of crashing on startup.
            self._fallback_to_cpu()

    def transcribe(
        self,
        audio_path: Path,
        language: str = "ko",
        progress_cb: Callable[[float], None] | None = None,
    ) -> str:
        try:
            return self._run(audio_path, language, progress_cb)
        except Exception:
            if self._device != "cuda":
                raise
            # cuBLAS/cuDNN only get touched on the first real inference call, so a
            # broken GPU runtime can surface here even though construction above
            # succeeded. Fall back to CPU once instead of crashing the pipeline.
            self._fallback_to_cpu()
            return self._run(audio_path, language, progress_cb)

    def _fallback_to_cpu(self) -> None:
        self._device = "cpu"
        if self._model_size.startswith("large"):
            self._model_size = CPU_FALLBACK_MODEL_SIZE
        self.model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(MODEL_DIR),
        )

    def _run(
        self,
        audio_path: Path,
        language: str,
        progress_cb: Callable[[float], None] | None,
    ) -> str:
        segments, info = self.model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            # Long lecture audio has silence/noise stretches where Whisper can
            # get stuck echoing its own previous output. Disabling
            # cross-segment conditioning and penalizing repeats keeps it from
            # looping on the same sentence.
            condition_on_previous_text=False,
            repetition_penalty=1.1,
            no_repeat_ngram_size=3,
        )

        lines = []
        for seg in segments:
            timestamp = f"[{_fmt(seg.start)} -> {_fmt(seg.end)}]"
            lines.append(f"{timestamp} {seg.text.strip()}")
            if progress_cb and info.duration:
                progress_cb(min(seg.end / info.duration, 1.0))

        return "\n".join(lines)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
