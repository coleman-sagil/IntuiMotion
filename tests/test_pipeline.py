from intuimotion.gestures import GestureInterpreter
from intuimotion.pipeline import HandFramePipeline

from tests.fakes import FakeHand, FakePalm


def _pipeline(config=None):
    return HandFramePipeline(config or {})


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
