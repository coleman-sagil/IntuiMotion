import os

from .actions import mouse, windows
from .dispatcher import ActionDispatcher
from .gestures import GestureInterpreter, TwoHandGestureDetector

# Per-frame pinch/grab/velocity dump for live threshold tuning against real
# hand data -- separate from INTUIMOTION_DRY_RUN since you may want to watch
# real numbers while real actions are still firing.
_DEBUG_HAND = os.environ.get("INTUIMOTION_DEBUG_HAND", "").lower() in ("1", "true", "yes")

# Mouse button state mirrors pinch state directly (press on pinch-start,
# release on pinch-end) rather than being a configurable one-shot action --
# tap-vs-drag falls out of how long the pinch is held, same as a real mouse
# button, so this is structural like cursor movement, not dispatcher-routed.
_MOUSE_BUTTON_EVENTS = {
    "left_press": lambda: mouse.press("left"),
    "left_release": lambda: mouse.release("left"),
    "right_press": lambda: mouse.press("right"),
    "right_release": lambda: mouse.release("right"),
}

_TWO_HAND_EVENTS = {
    "minimize_all": lambda: windows.minimize_all_except_terminal(),
}


class HandFramePipeline:
    """Wires per-hand and per-frame Leap events to gesture interpretation
    and dispatch. Pulled out of main.run() so it's testable without a live
    connection -- feed it hands/frames directly.
    """

    def __init__(self, config):
        self.dispatcher = ActionDispatcher(config)
        # One interpreter per hand (keyed by LeapC's HandType) rather than
        # one shared instance -- sharing state meant a left and right hand
        # in view at once fought over the same mode/pinch state (confirmed
        # live: clicks logged as alternating between hands that weren't
        # doing the clicking).
        self.interpreters = {}
        self.two_hand_detector = TwoHandGestureDetector()

    def on_hand_frame(self, hand):
        interpreter = self.interpreters.setdefault(hand.type, GestureInterpreter())
        if _DEBUG_HAND:
            vx, vy, vz = hand.palm.velocity
            print(
                f"[debug:{interpreter.mode}] {hand.type} "
                f"pinch={hand.pinch_strength:.2f} grab={hand.grab_strength:.2f} "
                f"vel=({vx:.0f},{vy:.0f},{vz:.0f})"
            )
        mode, events, pointer_position = interpreter.update(hand)
        self._handle_events(mode, events)
        if pointer_position is not None:
            mouse.move_to_leap_position(pointer_position.x, pointer_position.y)

    def on_tracking_frame(self, hands):
        # Runs for every hand with state, not just ones present this frame --
        # a hand that left tracking mid-drag needs its stale button released
        # even though it no longer shows up in `hands`.
        for interpreter in self.interpreters.values():
            self._handle_events(interpreter.mode, interpreter.check_staleness())

        two_hand_event = self.two_hand_detector.update(hands)
        if two_hand_event is not None:
            print(f"[two-hand] {two_hand_event}")
            action = _TWO_HAND_EVENTS.get(two_hand_event)
            if action is not None:
                action()

    def _handle_events(self, mode, events):
        for event in events:
            print(f"[{mode}] {event.name} ({event.hand_type})")
            mouse_action = _MOUSE_BUTTON_EVENTS.get(event.name)
            if mouse_action is not None:
                mouse_action()
            else:
                self.dispatcher.dispatch(event.name)
