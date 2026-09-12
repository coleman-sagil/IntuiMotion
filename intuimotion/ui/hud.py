"""Small always-on-top HUD overlay showing live mode + last gesture.

Shows itself whenever the pipeline reports activity and gets out of the way
~2.5s after the hand leaves the sensor, so there's nothing permanently
parked on screen for a daemon that is idle most of the time.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..gestures import Mode

# How long the HUD lingers after the last signal from the pipeline. Roughly
# "the hand left the sensor" -- there is no hand-lost event from LeapC (see
# GestureInterpreter.check_staleness), so silence is the only signal.
AUTO_HIDE_MS = 2500

SCREEN_MARGIN = 28  # px inset from the corner of the available screen area

MODE_COLORS = {
    Mode.IDLE: "#9aa0a6",  # grey -- tracking, but nothing engaged
    Mode.POINTER: "#4a9eff",  # blue -- absolute pointer
    Mode.MOUSE: "#3ecf6d",  # green -- relative touchpad
}
_UNKNOWN_MODE_COLOR = "#9aa0a6"

MODE_LABELS = {
    Mode.IDLE: "Idle",
    Mode.POINTER: "Pointer",
    Mode.MOUSE: "Mouse",
}


class Hud(QWidget):
    """Frameless translucent overlay pinned near the bottom-right corner.

    Connect it to a `UiBridge` with `connect_bridge()`. All three bridge
    signals are emitted from the Leap tracking thread; because both the
    bridge and this widget live on the GUI thread, PyQt6 queues those
    deliveries automatically and every slot below runs on the GUI thread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # An overlay that stole focus would interrupt whatever the user is
        # actually pointing at, and one that ate clicks would be worse -- the
        # whole point of the app is driving the cursor.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowTitle("Intuimotion HUD")

        self._panel = QFrame(self)
        self._panel.setObjectName("hudPanel")
        self._panel.setStyleSheet(
            "#hudPanel {"
            "  background-color: rgba(20, 22, 26, 205);"
            "  border: 1px solid rgba(255, 255, 255, 40);"
            "  border-radius: 10px;"
            "}"
        )

        self._mode_label = QLabel(MODE_LABELS[Mode.IDLE], self._panel)
        self._gesture_label = QLabel("", self._panel)
        self._gesture_label.setStyleSheet(
            "color: rgba(235, 238, 245, 190); font-size: 11px;"
        )

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(14, 10, 14, 10)
        panel_layout.setSpacing(2)
        panel_layout.addWidget(self._mode_label)
        panel_layout.addWidget(self._gesture_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._panel)

        # A single restartable timer rather than a fresh QTimer.singleShot per
        # signal: singleShot timers can't be cancelled, so a burst of frames
        # would queue a pile of hide() calls and the earliest one would hide
        # the HUD while a hand was still being tracked. start() on one timer
        # restarts the countdown instead.
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(AUTO_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)

        self.set_mode(Mode.IDLE)
        self.adjustSize()
        self.move_to_corner()

    def connect_bridge(self, bridge):
        """Wire this HUD to a UiBridge's three signals."""
        bridge.mode_changed.connect(self.on_mode_changed)
        bridge.gesture_fired.connect(self.on_gesture_fired)
        bridge.activity.connect(self.on_activity)

    # -- slots ---------------------------------------------------------

    def on_mode_changed(self, mode):
        self.set_mode(mode)
        self.poke()

    def on_gesture_fired(self, gesture_name, hand_type):
        hand = _short_hand_type(hand_type)
        self._gesture_label.setText(f"{gesture_name} · {hand}" if hand else gesture_name)
        self._resize_to_content()
        self.poke()

    def on_activity(self):
        self.poke()

    # -- behaviour -----------------------------------------------------

    def set_mode(self, mode):
        color = MODE_COLORS.get(mode, _UNKNOWN_MODE_COLOR)
        self._mode_label.setText(MODE_LABELS.get(mode, str(mode).title()))
        self._mode_label.setStyleSheet(
            f"color: {color}; font-size: 15px; font-weight: 600;"
        )
        self._resize_to_content()

    def poke(self):
        """Show the HUD and restart the auto-hide countdown."""
        if not self.isVisible():
            self.move_to_corner()
            self.show()
        self._hide_timer.start()

    def move_to_corner(self):
        """Pin to the bottom-right of the primary screen's available area.

        availableGeometry (not geometry) so the HUD sits above panels/docks
        rather than underneath them.
        """
        screen = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        size = self.sizeHint()
        self.move(
            area.right() - size.width() - SCREEN_MARGIN,
            area.bottom() - size.height() - SCREEN_MARGIN,
        )

    def _resize_to_content(self):
        self.adjustSize()
        if self.isVisible():
            self.move_to_corner()


def _short_hand_type(hand_type):
    """LeapC hand types stringify as e.g. "HandType.Left"; the enum name is
    just noise in a two-line overlay."""
    text = str(hand_type)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()
