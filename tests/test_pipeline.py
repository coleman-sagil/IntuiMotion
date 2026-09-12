from intuimotion.gestures import GestureInterpreter, Mode
from intuimotion.pipeline import HandFramePipeline

from tests.fakes import FakeHand, FakePalm


def _pipeline(config=None, ui_bridge=None):
    return HandFramePipeline(config or {}, ui_bridge=ui_bridge)


class FakeSignal:
    """Stand-in for a Qt signal that just records its emit() calls, so the
    ui_bridge tests stay entirely Qt-free -- the pipeline only ever calls
    .emit() on these, and must never import PyQt6 itself.
    """

    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


class FakeUiBridge:
    def __init__(self):
        self.mode_changed = FakeSignal()
        self.gesture_fired = FakeSignal()
        self.activity = FakeSignal()


def _pad_hand(position=(10, 120, 20), **kwargs):
    # Y inside GestureInterpreter's default mouse_active_y_range, i.e. the
    # hand is "resting on the pad" and the Mode.MOUSE clutch is engaged.
    return FakeHand(hand_type="Right", palm=FakePalm(position=position), **kwargs)


def _blade_hand(hand_type):
    return FakeHand(
        hand_type=hand_type,
        grab_strength=0.0,
        index_tip=(0, 0, 0),
        middle_tip=(5, 0, 0),
        ring_tip=(10, 0, 0),
        pinky_tip=(15, 0, 0),
        palm=FakePalm(position=(0, 0, 0)),
    )


def test_each_hand_type_gets_its_own_interpreter():
    pipeline = _pipeline()

    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.95))
    pipeline.on_hand_frame(FakeHand(hand_type="Left", pinch_strength=0.0))

    assert pipeline.interpreters["Right"] is not pipeline.interpreters["Left"]
    assert pipeline.interpreters["Right"]._was_pinching is True
    assert pipeline.interpreters["Left"]._was_pinching is False


def test_mouse_button_events_call_mpx_mouse_module_directly_not_dispatcher(monkeypatch):
    pipeline = _pipeline()
    pipeline.interpreters["Right"] = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)

    mouse_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.press",
        lambda hand_type, button: mouse_calls.append((hand_type, "press", button)),
    )
    dispatch_calls = []
    monkeypatch.setattr(pipeline.dispatcher, "dispatch", lambda name: dispatch_calls.append(name))

    pipeline.on_hand_frame(FakeHand(hand_type="Right"))  # engages pointer mode
    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.9))  # left_press

    assert ("Right", "press", "left") in mouse_calls
    assert "left_press" not in dispatch_calls


def test_mouse_button_events_route_to_the_hand_that_pinched(monkeypatch):
    # Left and Right hands must drive separate MPX cursors -- a press from
    # one hand should never carry the other hand's identity.
    pipeline = _pipeline()
    pipeline.interpreters["Left"] = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    pipeline.interpreters["Right"] = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)

    mouse_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.press",
        lambda hand_type, button: mouse_calls.append((hand_type, button)),
    )

    pipeline.on_hand_frame(FakeHand(hand_type="Left"))  # engage left
    pipeline.on_hand_frame(FakeHand(hand_type="Right"))  # engage right
    pipeline.on_hand_frame(FakeHand(hand_type="Left", pinch_strength=0.9))  # left hand press
    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.9))  # right hand press

    assert ("Left", "left") in mouse_calls
    assert ("Right", "left") in mouse_calls


def test_non_mouse_events_go_through_dispatcher(monkeypatch):
    pipeline = _pipeline()
    dispatch_calls = []
    monkeypatch.setattr(pipeline.dispatcher, "dispatch", lambda name: dispatch_calls.append(name))

    pipeline.on_hand_frame(FakeHand(hand_type="Right", palm=FakePalm(velocity=(800, 0, 0))))

    assert "swipe_right" in dispatch_calls


def test_pointer_position_triggers_cursor_move(monkeypatch):
    pipeline = _pipeline()
    pipeline.interpreters["Right"] = GestureInterpreter(engage_dwell=0.0)

    move_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.move_to_leap_position",
        lambda hand_type, x, y: move_calls.append((hand_type, x, y)),
    )

    pipeline.on_hand_frame(FakeHand(hand_type="Right", palm=FakePalm(position=(10, 20, 30))))

    assert move_calls == [("Right", 10, 20)]


def test_pointer_delta_triggers_relative_cursor_move(monkeypatch):
    # Mode.MOUSE's counterpart to test_pointer_position_triggers_cursor_move:
    # the raw Leap-mm delta goes straight to the relative-move action, un-
    # scaled -- pixel scaling belongs to the action layer, not here.
    pipeline = _pipeline()
    pipeline.set_engage_mode(Mode.MOUSE)

    move_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.move_by_leap_delta",
        lambda hand_type, dx, dz: move_calls.append((hand_type, dx, dz)),
        raising=False,  # action-layer sibling lands in parallel with this
    )

    pipeline.on_hand_frame(_pad_hand())  # creates the interpreter, still idle
    interpreter = pipeline.interpreters["Right"]
    assert interpreter.engage_mode == Mode.MOUSE
    interpreter.engage_dwell = 0.0

    pipeline.on_hand_frame(_pad_hand((10, 120, 20)))  # engages Mode.MOUSE
    assert interpreter.mode == Mode.MOUSE
    pipeline.on_hand_frame(_pad_hand((15, 120, 25)))  # 5mm right, 5mm forward

    # First in-band frame seeds the reference (no jump), then a real delta.
    assert move_calls == [("Right", 0.0, 0.0), ("Right", 5, 5)]


def test_engaging_in_mouse_mode_does_not_move_the_cursor_absolutely(monkeypatch):
    pipeline = _pipeline()
    pipeline.set_engage_mode(Mode.MOUSE)

    absolute_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.move_to_leap_position",
        lambda hand_type, x, y: absolute_calls.append((hand_type, x, y)),
    )
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.move_by_leap_delta",
        lambda hand_type, dx, dz: None,
        raising=False,
    )

    pipeline.on_hand_frame(_pad_hand())
    pipeline.interpreters["Right"].engage_dwell = 0.0
    pipeline.on_hand_frame(_pad_hand())
    pipeline.on_hand_frame(_pad_hand((15, 120, 25)))

    assert absolute_calls == []


def test_set_engage_mode_updates_already_created_interpreters():
    # Flipping the UI's mode switch has to reach hands that are already
    # being tracked, not just ones that show up afterwards.
    pipeline = _pipeline()
    pipeline.interpreters["Right"] = GestureInterpreter(engage_dwell=0.0)
    assert pipeline.interpreters["Right"].engage_mode == Mode.POINTER

    pipeline.set_engage_mode(Mode.MOUSE)

    assert pipeline.engage_mode == Mode.MOUSE
    assert pipeline.interpreters["Right"].engage_mode == Mode.MOUSE


def test_ui_bridge_receives_mode_and_activity_per_hand_frame():
    bridge = FakeUiBridge()
    pipeline = _pipeline(ui_bridge=bridge)

    pipeline.on_hand_frame(FakeHand(hand_type="Right"))

    assert bridge.mode_changed.emissions == [(Mode.IDLE,)]
    assert bridge.activity.emissions == [()]


def test_ui_bridge_receives_fired_gestures_with_a_string_hand_key():
    bridge = FakeUiBridge()
    pipeline = _pipeline(ui_bridge=bridge)

    pipeline.on_hand_frame(FakeHand(hand_type="Right", palm=FakePalm(velocity=(800, 0, 0))))

    assert bridge.gesture_fired.emissions == [("swipe_right", "Right")]


def test_ui_bridge_receives_staleness_release_events():
    # _handle_events is shared with on_tracking_frame, so stale releases have
    # to reach the UI too -- otherwise it would show a button stuck down.
    bridge = FakeUiBridge()
    pipeline = _pipeline(ui_bridge=bridge)
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    pipeline.interpreters["Right"] = interpreter

    pipeline.on_hand_frame(FakeHand(hand_type="Right"))  # engage
    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.9))  # left_press
    interpreter._last_seen -= 10.0

    pipeline.on_tracking_frame([])

    assert ("left_release", "Right") in bridge.gesture_fired.emissions


def test_pipeline_works_without_a_ui_bridge():
    # The daemon runs headless; ui_bridge stays fully optional.
    pipeline = _pipeline()
    assert pipeline.ui_bridge is None

    pipeline.interpreters["Right"] = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    pipeline.on_hand_frame(FakeHand(hand_type="Right"))  # engage, no crash
    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.9))  # left_press
    pipeline.on_tracking_frame([])

    assert pipeline.interpreters["Right"].mode == Mode.POINTER


def test_on_tracking_frame_releases_stale_button(monkeypatch):
    pipeline = _pipeline()
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    pipeline.interpreters["Right"] = interpreter

    pipeline.on_hand_frame(FakeHand(hand_type="Right"))  # engage
    pipeline.on_hand_frame(FakeHand(hand_type="Right", pinch_strength=0.9))  # left_press
    assert interpreter._was_pinching

    release_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.mpx_mouse.release",
        lambda hand_type, button: release_calls.append((hand_type, button)),
    )
    interpreter._last_seen -= 10.0  # simulate the hand having left tracking a while ago

    pipeline.on_tracking_frame([])  # hand no longer present this frame

    assert ("Right", "left") in release_calls
    assert not interpreter._was_pinching


def test_on_tracking_frame_triggers_minimize_all_after_hold(monkeypatch):
    pipeline = _pipeline()
    pipeline.two_hand_detector.hold_dwell = 0.0

    minimize_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.windows.minimize_all_except_terminal",
        lambda: minimize_calls.append(True),
    )

    pipeline.on_tracking_frame([_blade_hand("Left"), _blade_hand("Right")])

    assert minimize_calls == [True]


def test_on_tracking_frame_does_not_trigger_minimize_with_one_hand(monkeypatch):
    pipeline = _pipeline()
    pipeline.two_hand_detector.hold_dwell = 0.0

    minimize_calls = []
    monkeypatch.setattr(
        "intuimotion.pipeline.windows.minimize_all_except_terminal",
        lambda: minimize_calls.append(True),
    )

    pipeline.on_tracking_frame([_blade_hand("Left")])

    assert minimize_calls == []
