from intuimotion.gestures import GestureInterpreter, Mode


class FakeVector(tuple):
    @property
    def x(self):
        return self[0]

    @property
    def y(self):
        return self[1]

    @property
    def z(self):
        return self[2]


class FakePalm:
    def __init__(self, position=(0, 0, 0), velocity=(0, 0, 0)):
        self.position = FakeVector(position)
        self.velocity = FakeVector(velocity)


class FakeBone:
    def __init__(self, next_joint=(0, 0, 0)):
        self.next_joint = FakeVector(next_joint)


class FakeDigit:
    def __init__(self, tip=(0, 0, 0)):
        self.distal = FakeBone(tip)


class FakeHand:
    def __init__(
        self,
        pinch_strength=0.0,
        grab_strength=0.0,
        palm=None,
        hand_type="Right",
        thumb_tip=(0, 0, 0),
        middle_tip=(1000, 1000, 1000),  # far apart by default -- no middle-pinch
    ):
        self.pinch_strength = pinch_strength
        self.grab_strength = grab_strength
        self.palm = palm or FakePalm()
        self.type = hand_type
        self.thumb = FakeDigit(thumb_tip)
        self.middle = FakeDigit(middle_tip)


def test_pinch_fires_once_per_pinch_while_idle():
    interpreter = GestureInterpreter(pinch_threshold=0.8)
    hand = FakeHand(pinch_strength=0.9)

    _, events_first, _ = interpreter.update(hand)
    _, events_second, _ = interpreter.update(hand)

    assert [e.name for e in events_first] == ["pinch"]
    assert events_second == []


def test_swipe_detected_from_palm_velocity():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0)
    hand = FakeHand(palm=FakePalm(velocity=(800, 0, 0)))

    _, events, _ = interpreter.update(hand)

    assert [e.name for e in events] == ["swipe_right"]


def test_open_still_hand_engages_pointer_mode_after_dwell():
    interpreter = GestureInterpreter(engage_dwell=0.0)
    hand = FakeHand()

    mode, events, _ = interpreter.update(hand)

    assert mode == Mode.POINTER
    assert [e.name for e in events] == ["palm_engage"]


def test_fist_exits_pointer_mode():
    interpreter = GestureInterpreter(engage_dwell=0.0, grab_threshold=0.8)
    open_hand = FakeHand()
    interpreter.update(open_hand)  # engage pointer mode first
    assert interpreter.mode == Mode.POINTER

    fist = FakeHand(grab_strength=0.95)
    mode, events, _ = interpreter.update(fist)

    assert mode == Mode.IDLE
    assert [e.name for e in events] == ["fist_exit"]


def test_pinch_in_pointer_mode_fires_left_press_then_release():
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    open_hand = FakeHand()
    interpreter.update(open_hand)
    assert interpreter.mode == Mode.POINTER

    _, press_events, _ = interpreter.update(FakeHand(pinch_strength=0.9))
    assert [e.name for e in press_events] == ["left_press"]

    _, held_events, _ = interpreter.update(FakeHand(pinch_strength=0.9))
    assert held_events == []

    _, release_events, _ = interpreter.update(FakeHand(pinch_strength=0.0))
    assert [e.name for e in release_events] == ["left_release"]


def test_middle_pinch_in_pointer_mode_fires_right_press_then_release():
    interpreter = GestureInterpreter(engage_dwell=0.0, middle_pinch_distance=30.0)
    open_hand = FakeHand()
    interpreter.update(open_hand)
    assert interpreter.mode == Mode.POINTER

    close_hand = FakeHand(thumb_tip=(0, 0, 0), middle_tip=(10, 0, 0))
    _, press_events, _ = interpreter.update(close_hand)
    assert [e.name for e in press_events] == ["right_press"]

    far_hand = FakeHand(thumb_tip=(0, 0, 0), middle_tip=(1000, 0, 0))
    _, release_events, _ = interpreter.update(far_hand)
    assert [e.name for e in release_events] == ["right_release"]


def test_fist_mid_pinch_releases_mouse_buttons_instead_of_sticking():
    interpreter = GestureInterpreter(
        engage_dwell=0.0, pinch_threshold=0.8, grab_threshold=0.8, middle_pinch_distance=30.0
    )
    interpreter.update(FakeHand())  # engage pointer mode
    interpreter.update(FakeHand(pinch_strength=0.9, thumb_tip=(0, 0, 0), middle_tip=(10, 0, 0)))
    assert interpreter._was_pinching and interpreter._was_middle_pinching

    fist = FakeHand(grab_strength=0.95)
    mode, events, _ = interpreter.update(fist)

    assert mode == Mode.IDLE
    names = [e.name for e in events]
    assert "fist_exit" in names
    assert "left_release" in names
    assert "right_release" in names


def test_swipe_is_suppressed_while_a_pinch_is_held():
    interpreter = GestureInterpreter(pinch_threshold=0.8, swipe_speed_threshold=500.0)
    hand = FakeHand(pinch_strength=0.9)
    interpreter.update(hand)  # first frame: fires "pinch"

    still_pinching_and_moving = FakeHand(
        pinch_strength=0.9, palm=FakePalm(velocity=(800, 0, 0))
    )
    _, events, _ = interpreter.update(still_pinching_and_moving)

    assert events == []


def test_swipe_ignores_push_pull_motion_toward_sensor():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0)
    hand = FakeHand(palm=FakePalm(velocity=(0, 0, 800)))

    _, events, _ = interpreter.update(hand)

    assert events == []
