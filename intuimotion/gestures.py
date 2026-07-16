import time

OPEN_HAND_MAX_GRAB = 0.3
OPEN_HAND_MAX_PINCH = 0.3
STILL_SPEED_MAX = 150.0  # mm/s — rough "not actively moving" cutoff
STALE_HAND_TIMEOUT = 0.5  # seconds — see GestureInterpreter.check_staleness

FINGER_TOGETHER_MAX_GAP = 15.0  # mm, max gap between adjacent fingertips for a "blade hand"
PALMS_TOGETHER_MAX_DISTANCE = 150.0  # mm, max distance between the two palms
TWO_HAND_HOLD_DWELL = 1.2  # seconds — deliberately long, this triggers minimizing every window


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
        grab_dwell=0.15,
        exit_grace=0.25,
        swipe_speed_threshold=600.0,
        swipe_cooldown=0.6,
        middle_pinch_distance=30.0,
    ):
        self.pinch_threshold = pinch_threshold
        self.grab_threshold = grab_threshold
        self.engage_dwell = engage_dwell
        self.grab_dwell = grab_dwell
        self.exit_grace = exit_grace
        self.swipe_speed_threshold = swipe_speed_threshold
        self.swipe_cooldown = swipe_cooldown
        self.middle_pinch_distance = middle_pinch_distance

        self.mode = Mode.IDLE
        self._was_pinching = False
        self._was_middle_pinching = False
        self._was_grabbing = False
        self._engage_pose_since = None
        self._grab_pose_since = None
        self._grace_until = 0.0
        self._last_swipe_time = 0.0
        self._last_seen = time.time()

    def update(self, hand, now=None):
        """Process one hand's frame data.

        Returns (mode, events, pointer_position). `events` is a list of
        GestureEvent. `pointer_position` is the raw palm Vector to map to
        screen coordinates, set only while in pointer mode. `now` defaults
        to time.time() but can be passed explicitly for deterministic tests
        of the dwell timer and swipe cooldown.
        """
        if now is None:
            now = time.time()
        self._last_seen = now
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
                if self._engage_pose_since is None:
                    self._engage_pose_since = now
                if now - self._engage_pose_since >= self.engage_dwell:
                    self.mode = Mode.POINTER
                    self._engage_pose_since = None
                    events.append(GestureEvent("palm_engage", hand.type))
            else:
                self._engage_pose_since = None
                # Right after fist_exit, the hand is still physically
                # relaxing out of the fist shape -- that motion can look
                # like a swipe or brush past the pinch threshold. Ignore
                # idle-only gestures for exit_grace so only a genuinely new
                # gesture, not exit follow-through, fires one.
                if now >= self._grace_until:
                    if pinching:
                        if not self._was_pinching:
                            events.append(GestureEvent("pinch", hand.type))
                    else:
                        swipe_name = self._check_swipe(hand, speed, now)
                        if swipe_name:
                            events.append(GestureEvent(swipe_name, hand.type))

        elif self.mode == Mode.POINTER:
            middle_pinching = self._middle_pinch_distance(hand) <= self.middle_pinch_distance
            if grabbing:
                if self._grab_pose_since is None:
                    self._grab_pose_since = now
            else:
                self._grab_pose_since = None

            # A firm pinch naturally curls the other fingers too, so
            # grab_strength can spike past its threshold for a frame or two
            # mid-pinch. Requiring the grab pose to be held for grab_dwell
            # (not just seen once) filters that spike out -- a real fist
            # stays well past this dwell, a pinch-induced spike doesn't.
            if grabbing and now - self._grab_pose_since >= self.grab_dwell:
                self.mode = Mode.IDLE
                self._grace_until = now + self.exit_grace
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
        return _distance(hand.thumb.distal.next_joint, hand.middle.distal.next_joint)

    def check_staleness(self, now=None):
        """Force-release any held mouse button if this hand hasn't been
        updated recently.

        LeapC has no "hand lost" event (confirmed against the bindings'
        Listener callback list) -- a hand that leaves the tracking volume
        or gets occluded mid-drag just stops appearing in future frames.
        Without this, GestureInterpreter.update() would simply never run
        again for that hand, and a pressed mouse button would stay stuck
        down indefinitely. Call this once per tracking frame for every
        interpreter, not just the ones with hands present in that frame.
        """
        if now is None:
            now = time.time()
        if now - self._last_seen < STALE_HAND_TIMEOUT:
            return []

        events = []
        if self._was_pinching:
            events.append(GestureEvent("left_release", None))
            self._was_pinching = False
        if self._was_middle_pinching:
            events.append(GestureEvent("right_release", None))
            self._was_middle_pinching = False
        return events

    def _check_swipe(self, hand, speed, now):
        if speed < self.swipe_speed_threshold:
            return None

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


def _distance(v1, v2):
    dx = v1.x - v2.x
    dy = v1.y - v2.y
    dz = v1.z - v2.z
    return (dx * dx + dy * dy + dz * dz) ** 0.5


class TwoHandGestureDetector:
    """Detects gestures that need both hands at once.

    GestureInterpreter is deliberately per-hand and can't see the other
    hand -- that's what fixed the cross-talk bug where a shared interpreter
    misattributed events between hands. A genuinely two-handed gesture like
    this one needs a separate detector fed the whole frame's hand list, not
    a single hand.
    """

    def __init__(self, hold_dwell=TWO_HAND_HOLD_DWELL):
        self.hold_dwell = hold_dwell
        self._pose_since = None
        self._fired = False

    def update(self, hands, now=None):
        """Process one tracking frame's full hand list.

        Returns "minimize_all" once, after the pose (both hands open with
        fingers together, palms close) has been held continuously for
        `hold_dwell` seconds. Won't re-fire again until the pose breaks and
        re-forms, so it's one trigger per deliberate gesture, not a repeat
        every frame it's held.
        """
        if now is None:
            now = time.time()

        if len(hands) != 2 or not all(self._is_blade_hand(hand) for hand in hands):
            self._pose_since = None
            self._fired = False
            return None

        if _distance(hands[0].palm.position, hands[1].palm.position) > PALMS_TOGETHER_MAX_DISTANCE:
            self._pose_since = None
            self._fired = False
            return None

        if self._pose_since is None:
            self._pose_since = now
        if not self._fired and now - self._pose_since >= self.hold_dwell:
            self._fired = True
            return "minimize_all"
        return None

    @staticmethod
    def _is_blade_hand(hand):
        if hand.grab_strength > OPEN_HAND_MAX_GRAB:
            return False
        tips = [
            hand.index.distal.next_joint,
            hand.middle.distal.next_joint,
            hand.ring.distal.next_joint,
            hand.pinky.distal.next_joint,
        ]
        return all(_distance(a, b) <= FINGER_TOGETHER_MAX_GAP for a, b in zip(tips, tips[1:]))
