"""PyQt6 user interface for Intuimotion: system tray icon + on-screen HUD.

This package is the only place PyQt6 is imported. The capture / gesture /
action layers stay UI-framework-agnostic: `pipeline.HandFramePipeline` talks
to the UI exclusively through a duck-typed `ui_bridge` object (see
`intuimotion.ui.bridge.UiBridge`) that `main.py` constructs and hands in, so
nothing below this package imports Qt and nothing in this package imports
the pipeline.
"""
