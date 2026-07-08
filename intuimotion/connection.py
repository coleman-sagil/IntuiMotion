import leap


class TrackingListener(leap.Listener):
    """Bridges raw LeapC tracking events to a plain per-hand callback."""

    def __init__(self, on_hand_frame):
        super().__init__()
        self._on_hand_frame = on_hand_frame

    def on_connection_event(self, event):
        print("Connected to the Ultraleap tracking service.")

    def on_device_event(self, event):
        try:
            with event.device.open():
                info = event.device.get_info()
        except leap.exceptions.LeapCannotOpenDeviceError:
            # Raised both when the device is already open (get_info() below
            # will succeed) and on a genuine open failure (it won't) --
            # the try/except here is only for the former.
            try:
                info = event.device.get_info()
            except Exception as error:
                print(f"Could not open or read tracking device: {error}")
                return
        print(f"Tracking device found: {info.serial}")

    def on_tracking_event(self, event):
        for hand in event.hands:
            self._on_hand_frame(hand)


def build_connection(on_hand_frame):
    listener = TrackingListener(on_hand_frame)
    connection = leap.Connection()
    connection.add_listener(listener)
    return connection
