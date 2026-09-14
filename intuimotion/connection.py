"""Backwards-compatible entry point for building a hand-frame source.

Historically this module imported the vendor `leap` SDK at module scope and
built a LeapC connection directly, which meant IntuiMotion could not even be
*imported* without the proprietary Ultraleap bindings installed. That made the
vendor SDK a hard dependency of the whole application, on every platform,
forever -- exactly the coupling this project is removing.

The real implementations now live in `intuimotion.sources`, one module per
backend, each imported lazily. This module stays as a thin alias so existing
callers and docs keep working.
"""

from __future__ import annotations

from .sources import available_sources, build_source, resolve_name

__all__ = ["build_connection", "build_source", "available_sources", "resolve_name"]


def build_connection(on_hand_frame, on_tracking_frame=None, source=None, **kwargs):
    """Build the configured hand-frame source.

    Named "connection" for historical reasons; it returns a
    `sources.base.HandSource`, which exposes the same `.open()` context
    manager and `.set_tracking_mode()` the old vendor connection did.
    """
    return build_source(on_hand_frame, on_tracking_frame, name=source, **kwargs)
