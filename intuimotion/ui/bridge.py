from PyQt6.QtCore import QObject, pyqtSignal


class UiBridge(QObject):
    """Qt signal carrier between the (non-Qt) gesture pipeline and the UI.

    `HandFramePipeline` is handed one of these as its optional `ui_bridge`
    and only ever calls `.emit(...)` on these three signals -- it never
    imports Qt or this package, which keeps the capture/gesture/action
    layers UI-framework-agnostic.

    Thread affinity note: these signals are emitted from the Leap tracking
    callback thread, not the GUI thread. `main.py` constructs this object on
    the GUI thread before starting the connection, so the instance's thread
    affinity is the GUI thread and PyQt6 automatically upgrades every
    cross-thread connection to Qt.QueuedConnection -- slots run on the GUI
    thread. No explicit connection type or locking is needed here.
    """

    # Mode.* string (intuimotion.gestures.Mode), emitted for each processed
    # hand frame, reflecting whichever hand's mode was just computed.
    mode_changed = pyqtSignal(str)
    # (gesture_name, hand_type_as_plain_string), once per GestureEvent.
    gesture_fired = pyqtSignal(str, str)
    # Once per processed hand frame regardless of mode -- "a hand is present
    # right now". No payload; the UI uses it purely as a liveness heartbeat.
    activity = pyqtSignal()
