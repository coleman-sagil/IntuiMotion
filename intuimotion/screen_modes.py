"""Which kind of physical/virtual surface a calibration or control session
targets.

MONITOR and TV are both flat rectangular screens and share the same
corner-pointing calibration path (see calibration.py) -- geometrically
identical problems, just different typical sizes/mounting. AR and CAR are
explicitly NOT implemented yet: socketed here per Matthew's direction
(2026-07-27, "car screens is much much MUCH later, just socket this out in
preparation") so the architecture doesn't need reworking when they're
built, but there is no real behavior behind either today. AR in particular
is likely a genuinely different problem (no physical screen surface to
detect at all -- a virtual interface anchored in space instead), not just
a variant of the flat-rectangle case; don't assume it'll reuse this same
calibration path without a real design pass when that work starts.
"""


class ScreenMode:
    MONITOR = "monitor"
    TV = "tv"
    AR = "ar"
    CAR = "car"

    FLAT_RECTANGLE = (MONITOR, TV)
    NOT_YET_IMPLEMENTED = (AR, CAR)
    ALL = (MONITOR, TV, AR, CAR)


class ScreenModeNotImplementedError(NotImplementedError):
    """Raised when a mode in ScreenMode.NOT_YET_IMPLEMENTED is requested."""


def require_implemented(mode):
    if mode not in ScreenMode.ALL:
        raise ValueError(f"unknown screen mode {mode!r} -- expected one of {ScreenMode.ALL}")
    if mode in ScreenMode.NOT_YET_IMPLEMENTED:
        raise ScreenModeNotImplementedError(
            f"screen mode {mode!r} is socketed but not implemented yet"
        )
