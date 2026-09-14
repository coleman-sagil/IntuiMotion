"""Tests for the device-agnostic source layer.

The point of these is not that the synthetic backend "works" in the abstract,
but that the abstraction actually holds: a hand built by a backend must be
indistinguishable, to the gesture engine, from the LeapC hand the engine was
originally written against. If that stops being true, every backend breaks at
once -- so it is asserted directly rather than implied.
"""

import pytest

from intuimotion.gestures import GestureInterpreter, Mode
from intuimotion.sources import available_sources, build_source, resolve_name
from intuimotion.sources.base import Hand, HandSource, Palm, Vec3
from intuimotion.sources.synthetic import CYCLE_SECONDS, SyntheticSource, hand_for
from tests.fakes import FakeHand


class TestVec3:
    def test_supports_attribute_access(self):
        v = Vec3(1.0, 2.0, 3.0)
        assert (v.x, v.y, v.z) == (1.0, 2.0, 3.0)

    def test_supports_tuple_unpacking(self):
        # pipeline.py does `vx, vy, vz = hand.palm.velocity`.
        vx, vy, vz = Vec3(4.0, 5.0, 6.0)
        assert (vx, vy, vz) == (4.0, 5.0, 6.0)


class TestSchemaCompatibility:
    """The runtime Hand and the test FakeHand must expose the same surface."""

    def test_hand_exposes_every_attribute_the_gesture_engine_reads(self):
        hand = Hand()
        # Mirrors the attribute set grepped out of gestures.py.
        assert isinstance(hand.pinch_strength, float)
        assert isinstance(hand.grab_strength, float)
        assert hand.type in ("Left", "Right")
        hand.palm.position.x
        hand.palm.velocity.z
        for name in ("thumb", "index", "middle", "ring", "pinky"):
            digit = getattr(hand, name)
            digit.distal.next_joint.x
            assert isinstance(digit.is_extended, bool)

    def test_matches_the_fake_used_by_the_rest_of_the_suite(self):
        fake, real = FakeHand(), Hand()
        for name in ("pinch_strength", "grab_strength", "palm", "thumb", "index"):
            assert hasattr(fake, name) and hasattr(real, name)

    def test_hand_type_is_a_plain_string(self):
        # mpx_mouse._hand_key falls back to the value itself when there is no
        # .name, and Qt signals are typed for str -- so no enum is needed.
        assert Hand(hand_type="Left").type == "Left"


class TestFactory:
    def test_lists_backends(self):
        assert set(available_sources()) == {"synthetic", "openmotion", "leapc"}

    def test_builds_the_requested_backend(self):
        source = build_source(lambda hand: None, name="synthetic")
        assert isinstance(source, SyntheticSource)

    def test_unknown_backend_is_loud(self):
        with pytest.raises(ValueError, match="unknown source"):
            build_source(lambda hand: None, name="nope")

    def test_env_var_selects_backend(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SOURCE", "openmotion")
        assert resolve_name() == "openmotion"

    def test_explicit_name_beats_env(self, monkeypatch):
        monkeypatch.setenv("INTUIMOTION_SOURCE", "openmotion")
        assert resolve_name("synthetic") == "synthetic"

    def test_selecting_one_backend_does_not_need_another_installed(self):
        # The vendor SDK is absent here; building synthetic must still work.
        assert build_source(lambda hand: None, name="synthetic") is not None


class TestEmit:
    def test_emit_calls_both_callbacks(self):
        per_hand, per_frame = [], []
        source = HandSource(per_hand.append, per_frame.append)
        hands = [Hand(), Hand(hand_type="Left")]
        source.emit(hands)
        assert len(per_hand) == 2
        assert per_frame == [hands]

    def test_empty_frame_still_reaches_the_frame_callback(self):
        # An empty frame is how the pipeline learns a hand left the volume.
        per_frame = []
        HandSource(lambda hand: None, per_frame.append).emit([])
        assert per_frame == [[]]


class TestChoreography:
    def test_absent_beat_yields_no_hand(self):
        assert hand_for(0.5) is None

    def test_engage_beat_is_open_and_still(self):
        hand = hand_for(1.5)
        assert hand is not None
        # Must clear gestures.OPEN_HAND_MAX_* and STILL_SPEED_MAX.
        assert hand.pinch_strength < 0.3
        assert hand.grab_strength < 0.3
        assert max(abs(v) for v in hand.palm.velocity) < 150.0

    def test_pinch_beat_crosses_the_threshold(self):
        assert max(hand_for(t).pinch_strength for t in (5.2, 5.6, 6.0)) > 0.85

    def test_fist_beat_crosses_the_grab_threshold(self):
        assert max(hand_for(t).grab_strength for t in (9.6, 9.9, 10.0)) > 0.85

    def test_loops(self):
        a = hand_for(1.5)
        b = hand_for(1.5 + CYCLE_SECONDS)
        assert a.palm.position == b.palm.position

    def test_fingers_never_read_as_a_blade_hand(self):
        # Adjacent fingertips closer than FINGER_TOGETHER_MAX_GAP (15mm) would
        # trip the two-hand "minimize everything" gesture by accident.
        hand = hand_for(1.5)
        tips = [getattr(hand, n).distal.next_joint for n in ("index", "middle", "ring", "pinky")]
        gaps = [abs(b.x - a.x) for a, b in zip(tips, tips[1:])]
        assert min(gaps) > 15.0


class TestEndToEnd:
    """The synthetic choreography must drive the real gesture engine."""

    def _feed(self, interpreter, start, stop, fps=60.0):
        events = []
        step = 1.0 / fps
        t = start
        while t < stop:
            hand = hand_for(t)
            if hand is not None:
                _, fired, _, _ = interpreter.update(hand, now=t)
                events.extend(e.name for e in fired)
            t += step
        return events

    def test_engage_fires_and_enters_pointer_mode(self):
        interpreter = GestureInterpreter()
        events = self._feed(interpreter, 1.0, 2.2)
        assert "palm_engage" in events
        assert interpreter.mode == Mode.POINTER

    def test_full_cycle_presses_and_releases(self):
        interpreter = GestureInterpreter()
        events = self._feed(interpreter, 1.0, CYCLE_SECONDS)
        assert "palm_engage" in events
        assert "left_press" in events
        assert "left_release" in events
        assert events.index("left_press") < events.index("left_release")


class TestOpenMotionTransport:
    def test_binary_path_is_overridable(self, monkeypatch):
        # A packaged build / USB deployment must be able to say where the
        # driver actually shipped.
        monkeypatch.setenv("OPENMOTION_BINARY", "/opt/openmotion/openleap")
        from intuimotion.sources import openmotion

        assert openmotion.default_binary() == "/opt/openmotion/openleap"

    def test_frame_geometry_matches_the_driver(self):
        from intuimotion.sources import openmotion

        # Must stay in lockstep with rust-driver/src/lib.rs.
        assert openmotion.FRAME_BYTES == 1280 * 240
        assert openmotion.MAGIC == b"LFRM"
