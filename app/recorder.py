import queue
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1


class Recorder:
    """Streams microphone input to a WAV file until stop() is called."""

    def __init__(self, out_path: Path, device: int | None = None):
        self.out_path = out_path
        self.device = device
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._wave_file: wave.Wave_write | None = None
        self._active = False

    def _callback(self, indata, frames, time_info, status):
        self._queue.put(indata.copy())

    def start(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self._wave_file = wave.open(str(self.out_path), "wb")
        self._wave_file.setnchannels(CHANNELS)
        self._wave_file.setsampwidth(2)  # 16-bit PCM
        self._wave_file.setframerate(SAMPLE_RATE)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        self._active = True

    def drain(self) -> None:
        """Call periodically (e.g. from a UI timer) to flush buffered audio to disk."""
        while not self._queue.empty():
            chunk = self._queue.get_nowait()
            self._wave_file.writeframes(chunk.tobytes())

    def pause(self) -> None:
        """Stop pulling audio from the mic without closing the output file, so
        the paused stretch isn't written (and doesn't confuse the STT/summary
        step with dead air)."""
        self.drain()
        if self._stream and self._active:
            self._stream.stop()
            self._active = False

    def resume(self) -> None:
        if self._stream and not self._active:
            self._stream.start()
            self._active = True

    def stop(self) -> Path:
        self.drain()
        if self._stream:
            if self._active:
                self._stream.stop()
            self._stream.close()
        if self._wave_file:
            self._wave_file.close()
        return self.out_path

    @staticmethod
    def list_input_devices() -> list[dict]:
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]
