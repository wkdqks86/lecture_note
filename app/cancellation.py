class ProcessingCancelled(BaseException):
    """Unwinds a worker thread out of a long-running step when the user hits
    stop.

    Deliberately not an Exception subclass: Transcriber falls back from GPU to
    CPU on `except Exception`, so an ordinary exception raised from the
    progress callback would be swallowed and the whole transcription would
    start over on the CPU instead of stopping.
    """
