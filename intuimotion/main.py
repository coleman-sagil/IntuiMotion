import time

import leap

from .config import load_config
from .connection import build_connection
from .pipeline import HandFramePipeline


def run(config_path="config/gestures.yaml"):
    config = load_config(config_path)
    pipeline = HandFramePipeline(config)

    connection = build_connection(pipeline.on_hand_frame, pipeline.on_tracking_frame)
    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
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
