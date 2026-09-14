"""Legacy Ultraleap/LeapC source -- deprecated, kept only for comparison.

This is the vendor path IntuiMotion originally ran on. It is retained so an
existing install keeps working and so live behaviour can be compared against
our own driver, but it is **not** a supported direction:

  - it requires the proprietary Ultraleap hand-tracking service to be
    installed and running,
  - it requires the compiled `leapc-python-bindings`,
  - the vendor's distribution CDN is already dead at the TLS layer, so these
    components cannot be reinstalled from source on a new machine,
  - and it only ever supports UltraLeap hardware, which is the specific
    limitation this project exists to remove.

`import leap` happens inside `_startup()`, not at module import, so the
absence of the vendor SDK is never fatal to IntuiMotion -- it only fails if
someone explicitly selects this backend.
"""

from __future__ import annotations

from contextlib import contextmanager

from .base import HandSource

_MISSING = (
    "The legacy Ultraleap backend needs the vendor `leap` module "
    "(leapc-python-bindings) and the Ultraleap hand-tracking service, neither "
    "of which is installed here. This backend is deprecated -- use "
    "INTUIMOTION_SOURCE=openmotion (our own driver) or "
    "INTUIMOTION_SOURCE=synthetic (no hardware required)."
)


class LeapCSource(HandSource):
    """Adapter around the vendor SDK's own callback thread.

    The vendor connection runs its own background thread and delivers frames
    via a listener, so this overrides `open()` wholesale rather than
    implementing `_produce()`.
    """

    name = "leapc"

    def __init__(self, on_hand_frame, on_tracking_frame=None, tracking_mode="desktop"):
        super().__init__(on_hand_frame, on_tracking_frame)
        self.tracking_mode = tracking_mode
        self._leap = None
        self._connection = None

    def _build_listener(self, leap):
        source = self

        class _Listener(leap.Listener):
            def on_connection_event(self, event):
                print("[source:leapc] connected to the Ultraleap tracking service")

            def on_device_event(self, event):
                try:
                    with event.device.open():
                        info = event.device.get_info()
                except leap.exceptions.LeapCannotOpenDeviceError:
                    # Raised both when the device is already open (get_info
                    # below succeeds) and on a genuine failure (it won't).
                    try:
                        info = event.device.get_info()
                    except Exception as error:  # noqa: BLE001
                        print(f"[source:leapc] could not read device: {error}")
                        return
                print(f"[source:leapc] tracking device found: {info.serial}")

            def on_tracking_event(self, event):
                source.emit(list(event.hands))

        return _Listener()

    def set_tracking_mode(self, mode="desktop"):
        if self._connection is None or self._leap is None:
            return
        modes = {
            "desktop": self._leap.TrackingMode.Desktop,
            "hmd": self._leap.TrackingMode.HMD,
            "screentop": self._leap.TrackingMode.ScreenTop,
        }
        self._connection.set_tracking_mode(modes.get(mode, self._leap.TrackingMode.Desktop))

    @contextmanager
    def open(self):
        try:
            import leap
        except ImportError as error:
            raise RuntimeError(_MISSING) from error

        self._leap = leap
        self._connection = leap.Connection()
        self._connection.add_listener(self._build_listener(leap))
        with self._connection.open():
            self.set_tracking_mode(self.tracking_mode)
            try:
                yield self
            finally:
                self._connection = None
                self._leap = None
