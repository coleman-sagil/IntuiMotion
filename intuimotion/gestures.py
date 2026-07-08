import time

OPEN_HAND_MAX_GRAB = 0.3
OPEN_HAND_MAX_PINCH = 0.3
STILL_SPEED_MAX = 150.0  # mm/s -- rough "not actively moving" cutoff


class Mode:
    IDLE = "idle"
    POINTER = "pointer"


class GestureEvent:
    def __init__(self, name, hand_type):
        self.name = name
        self.hand_type = hand_type

    def __eq__(self, other):
        return (
            isinstance(other, GestureEvent)
            and self.name == other.name
            and self.hand_type == other.hand_type
        )

    def __repr__(self):
        return f"GestureEvent({self.name!r}, {self.hand_type})"


class GestureInterpreter:
    """Turns raw per-frame hand data into discrete gesture events plus pointer-mode state.

    Engaging pointer mode requires an open, still hand held for `engage_dwell`
    seconds rather than just "palm facing the sensor" -- for a desk-mounted
    controller, palm-down is the ambient resting orientation for every gesture,
    so orientation alone can't distinguish a deliberate activation from normal
    use. Stillness + an open hand, held, is the actual distinguishing signal.

    All thresholds below are untuned starting points.
    """

    def __init__(
        self,
        pinch_threshold=0.85,
        grab_threshold=0.85,
        engage_dwell=0.4,
        swipe_speed_threshold=600.0,
        swipe_cooldown=0.6,
        middle_pinch_distance=30.0,
    ):
        self.pinch_threshold = pinch_threshold
        self.grab_threshold = grab_threshold
        self.engage_dwell = engage_dwell
        self.swipe_speed_threshold = swipe_speed_threshold
        self.swipe_cooldown = swipe_cooldown
        self.middle_pinch_distance = middle_pinch_distance

        self.mode = Mode.IDLE
        self._was_pinching = False
        self._was_middle_pinching = False
        self._was_grabbing = False
        self._engage_pose_since = None
        self._last_swipe_time = 0.0

    def update(self, hand):
        """Process one hand's frame data.

        Returns (mode, events, pointer_position). `events` is a list of
        GestureEvent. `pointer_position` is the raw palm Vector to map to
        screen coordinates, set only while in pointer mode.
        """
        events = []
        pinch_strength = hand.pinch_strength
        grab_strength = hand.grab_strength
        pinching = pinch_strength >= self.pinch_threshold
        grabbing = grab_strength >= self.grab_threshold
        speed = _vector_length(hand.palm.velocity)

        if self.mode == Mode.IDLE:
            is_engage_pose = (
                grab_strength <= OPEN_HAND_MAX_GRAB
                and pinch_strength <= OPEN_HAND_MAX_PINCH
                and speed <= STILL_SPEED_MAX
            )
            if is_engage_pose:
                now = time.time()
                if self._engage_pose_since is None:
                    self._engage_pose_since = now
                if now - self._engage_pose_since >= self.engage_dwell:
                    self.mode = Mode.POINTER
                    self._engage_pose_since = None
                    events.append(GestureEvent("palm_engage", hand.type))
            else:
                self._engage_pose_since = None
                if pinching:
                    if not self._was_pinching:
                        events.append(GestureEvent("pinch", hand.type))
                else:
                    swipe_name = self._check_swipe(hand, speed)
                    if swipe_name:
                        events.append(GestureEvent(swipe_name, hand.type))

        elif self.mode == Mode.POINTER:
            middle_pinching = self._middle_pinch_distance(hand) <= self.middle_pinch_distance
            if grabbing and not self._was_grabbing:
                self.mode = Mode.IDLE
                events.append(GestureEvent("fist_exit", hand.type))
                # A fist mid-pinch would otherwise leave a mouse button
                # stuck down when pointer mode exits.
                if self._was_pinching:
                    events.append(GestureEvent("left_release", hand.type))
                if self._was_middle_pinching:
                    events.append(GestureEvent("right_release", hand.type))
                pinching = False
                middle_pinching = False
            else:
                if pinching and not self._was_pinching:
                    events.append(GestureEvent("left_press", hand.type))
                elif not pinching and self._was_pinching:
                    events.append(GestureEvent("left_release", hand.type))

                if middle_pinching and not self._was_middle_pinching:
                    events.append(GestureEvent("right_press", hand.type))
                elif not middle_pinching and self._was_middle_pinching:
                    events.append(GestureEvent("right_release", hand.type))

            self._was_middle_pinching = middle_pinching

        self._was_pinching = pinching
        self._was_grabbing = grabbing

        pointer_position = hand.palm.position if self.mode == Mode.POINTER else None
        return self.mode, events, pointer_position

    def _middle_pinch_distance(self, hand):
        # LeapC's own pinch_strength/pinch_distance are thumb-index only,
        # there's no equivalent built-in metric for thumb-middle -- computed
        # by hand the same way the upstream simple_pinching_example.py does
        # for thumb-index.
        thumb_tip = hand.thumb.distal.next_joint
        middle_tip = hand.middle.distal.next_joint
        dx = thumb_tip.x - middle_tip.x
        dy = thumb_tip.y - middle_tip.y
        dz = thumb_tip.z - middle_tip.z
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    def _check_swipe(self, hand, speed):
        if speed < self.swipe_speed_threshold:
            return None

        now = time.time()
        if now - self._last_swipe_time < self.swipe_cooldown:
            return None

        vx, vy, vz = hand.palm.velocity
        if abs(vz) >= abs(vx) and abs(vz) >= abs(vy):
            return None  # push/pull toward the sensor, not left-right/up-down

        self._last_swipe_time = now
        if abs(vx) >= abs(vy):
            return "swipe_right" if vx > 0 else "swipe_left"
        return "swipe_up" if vy > 0 else "swipe_down"


def _vector_length(vector):
    x, y, z = vector
    return (x * x + y * y + z * z) ** 0.5
