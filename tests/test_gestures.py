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


class FakeHand:
    def __init__(self, pinch_strength=0.0, grab_strength=0.0, palm=None, hand_type="Right"):
        self.pinch_strength = pinch_strength
        self.grab_strength = grab_strength
        self.palm = palm or FakePalm()
        self.type = hand_type


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


def test_pinch_in_pointer_mode_fires_click_not_pinch():
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    open_hand = FakeHand()
    interpreter.update(open_hand)
    assert interpreter.mode == Mode.POINTER

    pinching_hand = FakeHand(pinch_strength=0.9)
    _, events, _ = interpreter.update(pinching_hand)

    assert [e.name for e in events] == ["click"]
