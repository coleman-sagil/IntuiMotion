import os
import time

import leap

from .actions import mpx_mouse
from .actions.dry_run import set_enabled as set_dry_run
from .config import DEFAULT_CONFIG_PATH, load_config
from .connection import build_connection
from .pipeline import HandFramePipeline


def _dry_run_from_env():
    return os.environ.get("INTUIMOTION_DRY_RUN", "").lower() in ("1", "true", "yes")


def _no_ui_from_env():
    return os.environ.get("INTUIMOTION_NO_UI", "").lower() in ("1", "true", "yes")


def run(config_path=DEFAULT_CONFIG_PATH, dry_run=None, no_ui=None):
    if dry_run is None:
        dry_run = _dry_run_from_env()
    if no_ui is None:
        no_ui = _no_ui_from_env()
    set_dry_run(dry_run)

    config = load_config(config_path)

    if no_ui:
        # Headless path: no bridge, no Qt import at all. Keeps CI and
        # no-display boxes runnable without PyQt6 installed.
        pipeline = HandFramePipeline(config)
    else:
        # Imported lazily (not at module top level) so that merely importing
        # intuimotion.main, or running it with INTUIMOTION_NO_UI=1, never
        # requires PyQt6 or intuimotion.ui to be importable.
        from .ui.app import build_ui
        from .ui.bridge import UiBridge

        bridge = UiBridge()
        pipeline = HandFramePipeline(config, ui_bridge=bridge)

    if not dry_run:
        # Two MPX master pointers, one per hand -- real X resources, so
        # skipped entirely in dry-run (nothing to tear down either, then).
        mpx_mouse.setup()

    if not no_ui:
        # Built before the connection opens: leap's background thread starts
        # delivering frames (and therefore bridge emissions) as soon as the
        # connection is up, so the Qt objects receiving them must already
        # exist. tray_icon/hud are deliberately held as locals for the whole
        # of run() -- Qt drops widgets that nothing on the Python side
        # references, and they'd silently vanish mid-session otherwise.
        app, tray_icon, hud = build_ui(pipeline, bridge)

    connection = build_connection(pipeline.on_hand_frame, pipeline.on_tracking_frame)
    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
        if dry_run:
            print(
                "DRY RUN: no real mouse/keyboard/volume/window actions will happen, "
                "just logged."
            )
        print(
            "Intuimotion running. Hold an open, still hand over the sensor for "
            "~0.4s to engage pointer mode. Bring both open hands together, "
            "fingers closed, and hold to minimize every window except the "
            "terminal. Ctrl+C to quit."
        )
        if not no_ui:
            print(
                "Tray icon and HUD are live -- the tray menu picks which mode "
                "engaging your hand drops you into (pointer or mouse)."
            )
        try:
            if no_ui:
                while True:
                    time.sleep(1)
            else:
                # app.exec() returning (quit from the tray) is the normal
                # "we're done" signal here; Ctrl+C still works and is handled
                # below exactly as it was on the headless path.
                app.exec()
        except KeyboardInterrupt:
            print("Stopped.")
        finally:
            if not dry_run:
                mpx_mouse.teardown()


if __name__ == "__main__":
    run()
