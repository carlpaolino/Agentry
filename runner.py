"""Run pipeline stages from the dashboard: capture their printed output and turn exits into errors."""
import contextlib
import io


class StageError(Exception):
    def __init__(self, message: str, log: str):
        super().__init__(message)
        self.log = log


def call(fn, *args) -> str:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(*args)
    except SystemExit as e:
        log = buf.getvalue().strip()
        last = log.splitlines()[-1] if log else (str(e.code) if e.code else "stage stopped")
        raise StageError(last, log) from None
    except Exception as e:
        log = buf.getvalue().strip()
        raise StageError(f"{type(e).__name__}: {e}", log) from e
    return buf.getvalue().strip()
