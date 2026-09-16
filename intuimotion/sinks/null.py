"""No-op pointer sink -- logs instead of moving anything.

Two real uses, not just a test stub:

  1. The fallback when no backend is available (headless CI, a container, a
     Wayland box with no udev rule yet). The app stays fully runnable and
     says what it *would* have done, rather than refusing to start.
  2. Bring-up on a new platform: run the whole gesture stack and watch the
     pointer intent before wiring real injection.
"""

from __future__ import annotations

from .base import PointerSink


class NullPointer(PointerSink):
    name = "null"
    supports_multi_pointer = True  # nothing real to collide over

    def __init__(self, label="null", verbose=False):
        self.label = label
        self.verbose = verbose
        self.events = []  # inspected by tests

    def _record(self, text, event):
        self.events.append(event)
        if self.verbose:
            print(f"[sink:{self.label}] {text}")

    def move_to(self, x, y):
        self._record(f"move to ({int(x)}, {int(y)})", ("move_to", int(x), int(y)))

    def move_by(self, dx, dy):
        dx, dy = int(round(dx)), int(round(dy))
        self._record(f"move by ({dx}, {dy})", ("move_by", dx, dy))

    def press(self, button="left"):
        self._record(f"{button} down", ("press", button))

    def release(self, button="left"):
        self._record(f"{button} up", ("release", button))

    def close(self):
        self._record("closed", ("close",))
