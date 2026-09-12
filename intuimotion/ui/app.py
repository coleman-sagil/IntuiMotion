"""Builds the Qt UI layer: system tray icon + HUD overlay.

`build_ui()` deliberately does *not* call `app.exec()` -- the caller
(`main.py`) owns the event loop lifetime, since it also owns the Leap
connection that has to be opened before the loop blocks.

This module imports `intuimotion.gestures` (for `Mode`) and
`intuimotion.actions.dry_run`, but never `intuimotion.pipeline`: the live
`HandFramePipeline` arrives as an argument, and the `UiBridge` it was
constructed with arrives as the other one. That keeps the dependency edge
one-way (main.py -> ui, main.py -> pipeline) with no cycle.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..actions import dry_run
from ..gestures import Mode
from .hud import MODE_COLORS, MODE_LABELS, Hud

ICON_SIZE = 22  # px -- tray icons render around 16-22 on most panels

_IDLE_ICON_COLOR = "#c8ccd4"


def build_ui(pipeline, bridge):
    """Create (or reuse) the QApplication and build the tray icon + HUD.

    `pipeline` is the live HandFramePipeline; its mode-switch methods are
    wired straight to the tray menu. `bridge` must be the same UiBridge
    instance already passed to `HandFramePipeline(config, ui_bridge=...)`,
    and must have been created on this (the GUI) thread -- that thread
    affinity is what makes PyQt6 queue the pipeline thread's emissions onto
    the GUI thread automatically.

    Returns (app, tray_icon, hud_widget). Does not call app.exec().
    """
    app = QApplication.instance() or QApplication([])
    # The HUD auto-hides itself constantly; without this, the first auto-hide
    # would look like "last window closed" and tear the daemon down.
    app.setQuitOnLastWindowClosed(False)

    hud = Hud()
    hud.connect_bridge(bridge)

    tray = _build_tray(app, pipeline, bridge, hud)

    return app, tray, hud


def _build_tray(app, pipeline, bridge, hud):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        # Not fatal -- the HUD still works, and headless/tray-less sessions
        # shouldn't stop the daemon from running.
        print("[ui] No system tray available; tray icon may not appear.")

    tray = QSystemTrayIcon(app)
    menu = QMenu()

    mode_group = QActionGroup(menu)
    mode_group.setExclusive(True)

    pointer_action = QAction("Pointer (absolute)", menu)
    mouse_action = QAction("Mouse (touchpad)", menu)
    for action, mode in ((pointer_action, Mode.POINTER), (mouse_action, Mode.MOUSE)):
        action.setCheckable(True)
        mode_group.addAction(action)
        menu.addAction(action)
        # Default-arg binding, not closure capture -- a bare `mode` would let
        # both lambdas see the loop's final value.
        action.triggered.connect(lambda _checked, m=mode: pipeline.set_engage_mode(m))

    current_mode = getattr(pipeline, "engage_mode", Mode.POINTER)
    (mouse_action if current_mode == Mode.MOUSE else pointer_action).setChecked(True)

    menu.addSeparator()

    dry_run_action = QAction("Dry Run", menu)
    dry_run_action.setCheckable(True)
    dry_run_action.setChecked(dry_run.is_enabled())
    dry_run_action.toggled.connect(dry_run.set_enabled)
    menu.addAction(dry_run_action)

    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(lambda: QApplication.instance().quit())
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    # QMenu created without a parent isn't owned by anything Qt-side; hang it
    # off the tray so it isn't garbage-collected the moment we return.
    tray._menu = menu

    _apply_tray_mode(tray, Mode.IDLE)
    # Left-click the tray icon to peek at the HUD without waiting for a hand.
    tray.activated.connect(
        lambda reason: hud.poke()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    # mode_changed fires once per processed hand frame (~100/s with a hand in
    # view), so only touch the icon when the mode actually changed.
    bridge.mode_changed.connect(lambda mode: _on_mode_changed(tray, mode))

    tray.show()
    return tray


def _on_mode_changed(tray, mode):
    if getattr(tray, "_current_mode", None) == mode:
        return
    _apply_tray_mode(tray, mode)


def _apply_tray_mode(tray, mode):
    tray._current_mode = mode
    color = MODE_COLORS.get(mode, _IDLE_ICON_COLOR)
    tray.setIcon(make_tray_icon(color))
    tray.setToolTip(f"Intuimotion — {MODE_LABELS.get(mode, str(mode).title())}")


def make_tray_icon(color, size=ICON_SIZE):
    """Draw the tray glyph at runtime -- a ring with a solid centre, i.e. a
    crosshair/cursor target, tinted by the current mode.

    There is no icon asset in this repo and a tray icon that depends on an
    external file is one more thing to install wrong; QPainter costs nothing
    and stays crisp at panel sizes.
    """
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qcolor = QColor(color)

        ring_width = max(2, size // 9)
        inset = ring_width  # keep the stroke fully inside the pixmap
        pen = QPen(qcolor)
        pen.setWidth(ring_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            inset, inset, size - 2 * inset, size - 2 * inset
        )

        dot = max(4, size // 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(qcolor)
        painter.drawEllipse((size - dot) // 2, (size - dot) // 2, dot, dot)
    finally:
        painter.end()

    return QIcon(pixmap)
