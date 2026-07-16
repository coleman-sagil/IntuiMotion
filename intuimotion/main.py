import os
import time

import leap

from .actions.dry_run import set_enabled as set_dry_run
from .config import DEFAULT_CONFIG_PATH, load_config
from .connection import build_connection
from .pipeline import HandFramePipeline


def _dry_run_from_env():
    return os.environ.get("INTUIMOTION_DRY_RUN", "").lower() in ("1", "true", "yes")


def run(config_path=DEFAULT_CONFIG_PATH, dry_run=None):
    if dry_run is None:
        dry_run = _dry_run_from_env()
    set_dry_run(dry_run)

    config = load_config(config_path)
    pipeline = HandFramePipeline(config)

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
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    run()
