import time

import leap

from .actions import mouse
from .config import load_config
from .connection import build_connection
from .dispatcher import ActionDispatcher
from .gestures import GestureInterpreter


def run(config_path="config/gestures.yaml"):
    config = load_config(config_path)
    dispatcher = ActionDispatcher(config)
    interpreter = GestureInterpreter()

    def on_hand_frame(hand):
        mode, events, pointer_position = interpreter.update(hand)
        for event in events:
            print(f"[{mode}] {event.name} ({event.hand_type})")
            dispatcher.dispatch(event.name)
        if pointer_position is not None:
            mouse.move_to_leap_position(pointer_position.x, pointer_position.y)

    connection = build_connection(on_hand_frame)
    with connection.open():
        connection.set_tracking_mode(leap.TrackingMode.Desktop)
        print(
            "Intuimotion running. Hold an open, still hand over the sensor for "
            "~0.4s to engage pointer mode. Ctrl+C to quit."
        )
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    run()
