from intuimotion.gestures import GestureInterpreter, Mode, TwoHandGestureDetector

from tests.fakes import FakeHand, FakePalm


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


def test_swipe_left_detected_from_negative_x_velocity():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0)
    hand = FakeHand(palm=FakePalm(velocity=(-800, 0, 0)))

    _, events, _ = interpreter.update(hand)

    assert [e.name for e in events] == ["swipe_left"]


def test_swipe_up_detected_from_positive_y_velocity():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0)
    hand = FakeHand(palm=FakePalm(velocity=(0, 800, 0)))

    _, events, _ = interpreter.update(hand)

    assert [e.name for e in events] == ["swipe_up"]


def test_swipe_down_detected_from_negative_y_velocity():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0)
    hand = FakeHand(palm=FakePalm(velocity=(0, -800, 0)))

    _, events, _ = interpreter.update(hand)

    assert [e.name for e in events] == ["swipe_down"]


def test_swipe_cooldown_suppresses_second_swipe_too_soon():
    interpreter = GestureInterpreter(swipe_speed_threshold=500.0, swipe_cooldown=0.5)
    hand = FakeHand(palm=FakePalm(velocity=(800, 0, 0)))

    # Starting clock is deliberately non-zero: _last_swipe_time defaults to
    # 0.0, and a test clock starting at 0.0 would collide with that sentinel.
    _, first_events, _ = interpreter.update(hand, now=100.0)
    assert [e.name for e in first_events] == ["swipe_right"]

    _, second_events, _ = interpreter.update(hand, now=100.2)
    assert second_events == []

    _, third_events, _ = interpreter.update(hand, now=100.6)
    assert [e.name for e in third_events] == ["swipe_right"]


def test_engage_dwell_requires_sustained_hold_not_a_single_frame():
    interpreter = GestureInterpreter(engage_dwell=1.0)
    hand = FakeHand()

    mode, events, _ = interpreter.update(hand, now=0.0)
    assert mode == Mode.IDLE
    assert events == []

    mode, events, _ = interpreter.update(hand, now=0.5)
    assert mode == Mode.IDLE
    assert events == []

    mode, events, _ = interpreter.update(hand, now=1.0)
    assert mode == Mode.POINTER
    assert [e.name for e in events] == ["palm_engage"]


def test_engage_dwell_resets_if_pose_breaks_before_dwell_completes():
    interpreter = GestureInterpreter(engage_dwell=1.0, pinch_threshold=0.8)
    open_hand = FakeHand()
    pinching_hand = FakeHand(pinch_strength=0.9)  # breaks the "open hand" pose

    interpreter.update(open_hand, now=0.0)
    interpreter.update(pinching_hand, now=0.5)  # pose broken -- timer should reset
    mode, events, _ = interpreter.update(open_hand, now=1.0)  # only 0s into a fresh hold

    assert mode == Mode.IDLE
    assert events == []


def test_middle_pinch_distance_accounts_for_y_and_z_not_just_x():
    interpreter = GestureInterpreter(engage_dwell=0.0, middle_pinch_distance=30.0)
    interpreter.update(FakeHand())  # engage pointer mode

    # Thumb and middle share x -- if the distance calculation ignored y/z,
    # this would wrongly read as "together".
    far_in_y = FakeHand(thumb_tip=(0, 0, 0), middle_tip=(0, 1000, 0))
    _, events, _ = interpreter.update(far_in_y)
    assert events == []

    close_in_z = FakeHand(thumb_tip=(0, 0, 0), middle_tip=(0, 0, 10))
    _, events, _ = interpreter.update(close_in_z)
    assert [e.name for e in events] == ["right_press"]


def test_pointer_position_is_none_while_idle():
    interpreter = GestureInterpreter()
    hand = FakeHand(palm=FakePalm(position=(10, 20, 30)))

    _, _, pointer_position = interpreter.update(hand)

    assert pointer_position is None


def test_pointer_position_tracks_palm_while_in_pointer_mode():
    interpreter = GestureInterpreter(engage_dwell=0.0)
    hand = FakeHand(palm=FakePalm(position=(10, 20, 30)))

    _, _, pointer_position = interpreter.update(hand)

    assert interpreter.mode == Mode.POINTER
    assert (pointer_position.x, pointer_position.y, pointer_position.z) == (10, 20, 30)


def test_pointer_position_still_set_during_a_held_drag():
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    interpreter.update(FakeHand())  # engage

    dragging_hand = FakeHand(pinch_strength=0.9, palm=FakePalm(position=(5, 6, 7)))
    _, _, pointer_position = interpreter.update(dragging_hand)

    assert (pointer_position.x, pointer_position.y, pointer_position.z) == (5, 6, 7)


def test_check_staleness_releases_held_buttons_after_timeout():
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    interpreter.update(FakeHand(), now=0.0)
    interpreter.update(FakeHand(pinch_strength=0.9), now=0.1)
    assert interpreter._was_pinching

    events = interpreter.check_staleness(now=1.1)

    assert [e.name for e in events] == ["left_release"]
    assert not interpreter._was_pinching


def test_check_staleness_does_nothing_if_hand_seen_recently():
    interpreter = GestureInterpreter(engage_dwell=0.0, pinch_threshold=0.8)
    interpreter.update(FakeHand(), now=0.0)
    interpreter.update(FakeHand(pinch_strength=0.9), now=0.1)

    events = interpreter.check_staleness(now=0.2)

    assert events == []


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


def test_two_hand_detector_fires_after_sustained_hold():
    detector = TwoHandGestureDetector(hold_dwell=1.0)
    left, right = _blade_hand("Left"), _blade_hand("Right")

    assert detector.update([left, right], now=0.0) is None
    assert detector.update([left, right], now=0.5) is None
    assert detector.update([left, right], now=1.0) == "minimize_all"


def test_two_hand_detector_fires_only_once_while_held():
    detector = TwoHandGestureDetector(hold_dwell=0.0)
    left, right = _blade_hand("Left"), _blade_hand("Right")

    assert detector.update([left, right], now=0.0) == "minimize_all"
    assert detector.update([left, right], now=0.1) is None


def test_two_hand_detector_requires_exactly_two_hands():
    detector = TwoHandGestureDetector(hold_dwell=0.0)

    assert detector.update([_blade_hand("Left")], now=0.0) is None


def test_two_hand_detector_ignores_curled_fingers():
    detector = TwoHandGestureDetector(hold_dwell=0.0)
    curled = FakeHand(hand_type="Right", grab_strength=0.9, palm=FakePalm(position=(0, 0, 0)))

    assert detector.update([_blade_hand("Left"), curled], now=0.0) is None


def test_two_hand_detector_ignores_spread_fingers():
    detector = TwoHandGestureDetector(hold_dwell=0.0)
    spread = FakeHand(
        hand_type="Right",
        grab_strength=0.0,
        index_tip=(0, 0, 0),
        middle_tip=(100, 0, 0),
        ring_tip=(200, 0, 0),
        pinky_tip=(300, 0, 0),
        palm=FakePalm(position=(0, 0, 0)),
    )

    assert detector.update([_blade_hand("Left"), spread], now=0.0) is None


def test_two_hand_detector_requires_palms_close_together():
    detector = TwoHandGestureDetector(hold_dwell=0.0)
    far = FakeHand(
        hand_type="Right",
        grab_strength=0.0,
        index_tip=(0, 0, 0),
        middle_tip=(5, 0, 0),
        ring_tip=(10, 0, 0),
        pinky_tip=(15, 0, 0),
        palm=FakePalm(position=(5000, 0, 0)),
    )

    assert detector.update([_blade_hand("Left"), far], now=0.0) is None
