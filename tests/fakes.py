"""Fake LeapC hand/vector objects, duck-typed to match the real bindings'
datatypes.py closely enough for gesture-logic tests to run without hardware
or the compiled bindings.
"""


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
        index_tip=(0, 0, 0),
        ring_tip=(0, 0, 0),
        pinky_tip=(0, 0, 0),
    ):
        self.pinch_strength = pinch_strength
        self.grab_strength = grab_strength
        self.palm = palm or FakePalm()
        self.type = hand_type
        self.thumb = FakeDigit(thumb_tip)
        self.middle = FakeDigit(middle_tip)
        self.index = FakeDigit(index_tip)
        self.ring = FakeDigit(ring_tip)
        self.pinky = FakeDigit(pinky_tip)
