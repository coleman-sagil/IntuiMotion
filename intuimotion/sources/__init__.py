"""Pluggable hand-frame sources.

IntuiMotion's gesture engine, action layer and UI are entirely device-
agnostic: they consume the normalized `Hand` schema in `base.py` and nothing
else. Everything device-specific lives behind one of the backends here, which
is what lets the same application drive an UltraLeap sensor, our own
OpenMotion driver, a future depth/LiDAR/radar frontend, or no hardware at all.

Backends
--------
``synthetic``   Scripted gesture choreography. No hardware, no drivers, no
                permissions. Runs anywhere -- the default, and what makes the
                UI demoable and testable on any machine or OS.
``openmotion``  Our own reverse-engineered driver. No vendor software.
``leapc``       Legacy Ultraleap vendor SDK. Deprecated; see `leapc.py`.

Selection order: explicit argument, then ``INTUIMOTION_SOURCE``, then the
default. Adding a backend means adding one entry to ``_BACKENDS`` -- nothing
above this package changes.
"""

from __future__ import annotations

import os

from .base import DIGIT_NAMES, LEFT, RIGHT, Bone, Digit, Hand, HandSource, Palm, Vec3

DEFAULT_SOURCE = "synthetic"

__all__ = [
    "DIGIT_NAMES",
    "LEFT",
    "RIGHT",
    "Bone",
    "Digit",
    "Hand",
    "HandSource",
    "Palm",
    "Vec3",
    "available_sources",
    "build_source",
    "DEFAULT_SOURCE",
]


def _synthetic(*args, **kwargs):
    from .synthetic import SyntheticSource

    return SyntheticSource(*args, **kwargs)


def _openmotion(*args, **kwargs):
    from .openmotion import OpenMotionSource

    return OpenMotionSource(*args, **kwargs)


def _leapc(*args, **kwargs):
    from .leapc import LeapCSource

    return LeapCSource(*args, **kwargs)


# Constructors are indirected through the thunks above so that selecting one
# backend never imports another's dependencies -- picking `synthetic` must not
# require the vendor SDK to exist, and picking `leapc` must not require the
# OpenMotion binary to be present.
_BACKENDS = {
    "synthetic": _synthetic,
    "openmotion": _openmotion,
    "leapc": _leapc,
}


def available_sources():
    """Backend names, in preference order."""
    return tuple(_BACKENDS)


def resolve_name(name=None):
    if name:
        return name.strip().lower()
    return os.environ.get("INTUIMOTION_SOURCE", DEFAULT_SOURCE).strip().lower()


def build_source(on_hand_frame, on_tracking_frame=None, name=None, **kwargs):
    """Construct the selected backend.

    Raises `ValueError` with the valid options rather than falling back
    silently -- a typo in `INTUIMOTION_SOURCE` should be loud, not quietly
    route you to a different device than the one you asked for.
    """
    resolved = resolve_name(name)
    factory = _BACKENDS.get(resolved)
    if factory is None:
        raise ValueError(
            f"unknown source {resolved!r}; available: {', '.join(available_sources())}"
        )
    return factory(on_hand_frame, on_tracking_frame, **kwargs)
