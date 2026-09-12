# Intuimotion

Gesture-driven mouse/pointer control, macros, and media transport (volume,
track skip, play/pause) for the original Leap Motion Controller, built on
Ultraleap's Gemini tracking stack.

Companion setup/ops notes (install script, sensor bring-up) live in
`~/leap-motion-control`; this repo is the actual application code.

## Status

Confirmed working end to end against live hardware: connects, tracks, and
dispatches real mouse/media actions. See "Known gaps" below for what's
intentionally left untuned.

## Architecture

```
Leap Motion Controller (USB)
  -> Ultraleap Hand Tracking Service (system daemon)
  -> leapc-python-bindings (leap.Connection / leap.Listener)
  -> intuimotion.connection.TrackingListener      per-hand frame callback
  -> intuimotion.gestures.GestureInterpreter      raw hand data -> discrete gesture events + mode
  -> intuimotion.dispatcher.ActionDispatcher      gesture name -> config-mapped action
  -> intuimotion.actions.{mouse,media,macros}     pynput mouse / media keys / keystrokes / shell

intuimotion.pipeline.HandFramePipeline (optional ui_bridge)
  -> intuimotion.ui.bridge.UiBridge               3 Qt signals, GUI-thread affinity
  -> intuimotion.ui.{app,hud}                     tray icon + HUD overlay
```

Cursor movement (both absolute pointer position and relative mouse deltas)
bypasses the dispatcher and is wired directly in `pipeline.py`, since it's
continuous per-frame motion rather than a discrete triggered action.

`intuimotion/ui/` is the only place PyQt6 is imported, and it's imported
lazily — nothing below it imports Qt, and nothing in it imports the pipeline.

## Setup

1. Ultraleap Hand Tracking Service + Control Panel must already be installed
   and running (see `~/leap-motion-control/install_ultraleap.sh`).
2. Build the LeapC Python bindings against system Python (requires
   `python3.10-dev` for `Python.h`, and a C compiler — gcc is already present
   on this machine):
   ```
   sudo apt install -y python3.10-dev
   cd ~/leap-motion-control/leapc-python-bindings
   python3 -m build leapc-cffi
   pip install --user leapc-cffi/dist/leapc_cffi-0.0.1.tar.gz
   pip install --user -e leapc-python-api
   ```
3. Install this package:
   ```
   cd ~/Intuimotion
   pip install --user -e .
   ```
4. Run it:
   ```
   python -m intuimotion.main
   ```
   Or in dry-run mode, which logs every mouse/keyboard/volume/window action
   instead of actually performing it -- useful for testing gesture changes
   without your real cursor jumping around or your real volume changing:
   ```
   INTUIMOTION_DRY_RUN=1 python -m intuimotion.main
   ```

## Gestures (default `config/gestures.yaml`)

| Gesture | Trigger | Default action |
|---|---|---|
| `palm_engage` | open, still hand held ~0.4s | enters the selected engage mode (pointer or mouse) |
| `pinch` (idle) | thumb+index pinch while idle | play/pause |
| `left_press` / `left_release` (active mode) | thumb+index pinch start/end while in pointer or mouse mode | left mouse button down/up |
| `right_press` / `right_release` (active mode) | thumb+middle pinch start/end while in pointer or mouse mode | right mouse button down/up |
| `fist_exit` | fist held ~0.15s in pointer or mouse mode | exits to idle |
| `swipe_up` / `swipe_down` | fast vertical hand motion while idle | volume up / down |
| `swipe_right` / `swipe_left` | fast horizontal hand motion while idle | next / previous track |

Idle-only gestures (`pinch`, the four swipes) are briefly suppressed for
`exit_grace` (0.25s default) right after a `fist_exit`, so your hand
relaxing out of the fist shape doesn't misfire a volume change or
play/pause. `palm_engage` is unaffected -- open-still-hand re-engages
pointer mode at any time, grace window or not.

`palm_engage` and `fist_exit` always drive the internal mode switch itself
(that part is hardcoded, not configurable) — but like every other gesture
name, `ActionDispatcher` will also fire whatever action you attach to them in
`gestures.yaml`, if anything. Leave them out of the config (the default) and
they're just silent mode transitions.

Cursor position while in pointer mode is driven directly by palm position,
mapped from a Leap "interaction box" to screen pixels.

Mouse buttons mirror pinch state directly rather than firing a one-shot
click: press on pinch-start, release on pinch-end. A quick pinch reads as a
click, a held pinch reads as a drag — same as a real mouse button, no
tap-vs-hold timing logic needed. `left_press`/`left_release`/`right_press`/
`right_release` are wired directly in `main.py`, not configurable, for the
same reason cursor movement isn't: they need paired press/release calls
tied to the physical pinch timing, not a single fire-and-forget action.

Right-click uses thumb-to-middle-finger distance rather than LeapC's
built-in pinch metric, which is thumb-index only. Not yet verified whether
a normal thumb-index pinch can also trip the middle-finger threshold if the
fingers are held close together — worth checking with your actual hand
during testing.

Add custom macros (keystroke combos or shell commands) by adding entries to
`config/gestures.yaml` — see the commented example at the bottom of that
file. No code changes needed for a new keystroke or shell macro.

## Mouse mode (relative touchpad)

A second active mode alongside pointer mode. `palm_engage` drops a hand into
whichever of the two is currently selected (`Mode.POINTER` by default; switch
it from the tray menu, or call `pipeline.set_engage_mode(...)`). Pinch/click
and `fist_exit` behave identically in both — the modes differ only in how
hand motion becomes cursor motion.

| | Pointer (`Mode.POINTER`) | Mouse (`Mode.MOUSE`) |
|---|---|---|
| Mapping | absolute — palm position maps into a fixed interaction box | relative — per-frame change in hand position |
| Plane | X (left/right) + Y (up/down) | X (left/right) + Z (toward/away) |
| Cursor when hand is still | parked at the mapped position | doesn't move |
| Reachability | limited by `LEAP_X_RANGE`/`LEAP_Y_RANGE` | unbounded; re-clutch to keep going |
| Tuning constant | `LEAP_X_RANGE`/`LEAP_Y_RANGE` | `MOUSE_SENSITIVITY` (px per Leap mm) |

The sensor lies flat facing up, so X/Z is the "resting on a pad" plane your
hand already glides across on a real touchpad, and Y (height above the
sensor) becomes the clutch axis. While the palm is inside
`MOUSE_ACTIVE_Y_RANGE` (`gestures.py`, 60–180mm) the cursor tracks hand
motion; lift out of that band and `pointer_delta` goes `None`, so you can
reposition your hand without moving the cursor — same as lifting a real mouse
to re-center it. Settling back into the band seeds a fresh reference point and
emits a `(0, 0)` delta first, so re-entering never jumps the cursor.

Sign convention (a first guess, easy to flip during hardware tuning): Leap's
+z increases toward the user, so pushing the hand away moves the cursor up and
pulling back moves it down.

The mm→pixel scaling lives in the action layer
(`mouse.move_by_leap_delta` / `mpx_mouse.move_by_leap_delta`), mirroring the
existing `pointer_position`/`map_to_screen` split — `gestures.py` only ever
emits raw Leap millimeters. `MOUSE_SENSITIVITY` is defined once in
`actions/mouse.py` and imported by `mpx_mouse.py`, so both cursor paths tune
together.

## Tray icon + HUD

`intuimotion/ui/` is a PyQt6 system tray icon plus a small HUD overlay, built
by default when you run the daemon.

```
INTUIMOTION_NO_UI=1 python -m intuimotion.main
```
falls back to the old headless loop: no bridge, no tray, no HUD, and Qt is
never imported at all — so no-display boxes and CI stay runnable without
PyQt6 installed.

The tray menu picks which mode `palm_engage` drops you into (Pointer or
Mouse, exclusive), toggles dry-run live, and quits the daemon. Per
`gestures.py`'s design, switching mode only takes effect on a hand's *next*
engage; a hand already in a mode stays there until it fist-exits. The tray
glyph is drawn at runtime with QPainter (no icon asset in the repo) and is
tinted by the current mode — grey idle, blue pointer, green mouse. Left-click
the tray icon to peek at the HUD without waiting for a hand.

The HUD is a frameless, click-through, always-on-top panel in the bottom-right
of the primary screen's available area, showing the live mode and the last
gesture that fired. It auto-hides ~2.5s (`AUTO_HIDE_MS`) after the last signal
from the pipeline, which is the only available "hand left the sensor" cue —
LeapC has no hand-lost event (see `GestureInterpreter.check_staleness`).

`pipeline.HandFramePipeline` stays UI-framework-agnostic: it talks to the UI
only through a duck-typed optional `ui_bridge` (`ui/bridge.py`) carrying three
Qt signals — `mode_changed(str)`, `gesture_fired(str, str)`, `activity()`.
With `ui_bridge=None` the pipeline behaves exactly as it did before. Signals
are emitted from the Leap tracking thread; the bridge is constructed on the
GUI thread, so PyQt6 queues every delivery onto the GUI thread automatically.

## Boundary calibration (2026-07-27, supersedes the ritual below for touch-based screens)

`intuimotion/boundary_calibration.py` implements Matthew's revised
calibration UX: hold both pointer fingers out at the two top corners
until locked in place (hold-still, no fist), then trace both fingers down
along the screen's real physical edges to the bottom corners, holding
still again to lock the end point. Because the fingers stay on/near the
actual screen surface throughout, this measures each corner as a real 3D
position directly -- no known screen width/height needed, unlike the
ray-walking technique below, which is ambiguous without it (confirmed via
testing, see that section). `EdgeTracer.fitted_line()` smooths the raw
locked points against the full traced path via PCA, for robustness
against real hand tremor (validated on a synthetic noisy trace).

Recommended technique for MONITOR/TV. The older ray-walking approach
below is kept, not deleted -- it solves a genuinely different problem
(a position from a single ray with no scale reference) that may still
matter for a future non-touch scenario (e.g. AR, where there's nothing
physical to trace).

10 tests, including a noisy-trace recovery test and a regression guard
for a real design risk (holding still right after the start-lock, before
any real movement, must not immediately re-trigger the end-lock -- this
is what MIN_TRACE_SPAN_MM guards against).

## Screen calibration (ray-walking technique, needs real-world validation)

`intuimotion/calibration.py` implements the corner-pointing calibration
ritual: point at a screen corner, walk backward while staying pointed at
it, close a fist to solidify that corner, repeat for all 4 corners
(`top_left`, `top_right`, `bottom_right`, `bottom_left`, in that order).
Once all 4 are solidified, `solve_screen_plane` computes the screen's
actual corner points in Leap-space.

Requires the screen's real physical width/height in mm (`ScreenCalibrator`
takes them as required constructor args) -- confirmed via testing that
the ray geometry alone (right angles + equal sides + coplanar, no
absolute scale) is NOT enough to uniquely determine the rectangle; two
different rectangles can satisfy those same relative-shape constraints
for the same 4 rays. Known size is what actually pins down scale and
position.

Covers `ScreenMode.MONITOR` and `ScreenMode.TV` (same flat-rectangle
geometry). `ScreenMode.AR` and `ScreenMode.CAR` are socketed in
`screen_modes.py` but explicitly not implemented -- much later per
Matthew, and AR in particular is likely a genuinely different problem
(no physical screen surface to calibrate against at all).

16 tests, including two that validate the plane/corner solver against
known synthetic 3D ground-truth rectangles (not just mocked gesture
logic) -- see `tests/test_calibration.py`. Not yet run against a real
calibration session; every dwell/sample-count/span threshold is an
untuned starting point, same status the rest of this project's gesture
thresholds had before real-hardware tuning.

## Camera-based screen detection (merged from DeepLens-VT, 2026-08-01)

`intuimotion/camera.py` + `intuimotion/screen_detector.py`: OpenCV-based
webcam capture and screen/rectangle detection, absorbed from the
standalone `DeepLens-VT` prototype once that project's camera + screen
detection moved onto the same machine as the rest of IntuiMotion. Not yet
wired into the live gesture pipeline or run against a real camera — see
`docs/CAMERA_SCREEN_DETECTION.md` for what was and wasn't ported, and the
still-open coordinate-fusion design needed to actually turn this into a
"point at a real screen" feature.

## Known gaps (debugging/tuning, deferred on purpose)

- **Screen mapping bounds** (`LEAP_X_RANGE`/`LEAP_Y_RANGE` in
  `intuimotion/actions/mouse.py`) are untuned guesses. Expect jitter/dead
  zones until adjusted against this sensor's actual placement and your real
  hand range.
- **Pinch/grab/swipe/dwell thresholds** (`GestureInterpreter.__init__` in
  `intuimotion/gestures.py`) are untuned starting points. `grab_dwell`
  (0.15s) is a fixed value chosen from one live debug session — a firm
  pinch curls the other fingers enough to briefly spike `grab_strength`
  past its threshold, so `fist_exit` requires the fist pose to be held for
  `grab_dwell` before firing, rather than a single frame.
- **Mouse-mode tuning constants** (`MOUSE_SENSITIVITY` in
  `intuimotion/actions/mouse.py`, `MOUSE_ACTIVE_Y_RANGE` in
  `intuimotion/gestures.py`) are untuned guesses, exactly the same status as
  `LEAP_X_RANGE`/`LEAP_Y_RANGE` above — picked to feel roughly like a
  mid-sensitivity touchpad and a comfortable hand-resting height, never
  checked against real hand data. Unlike the absolute mapping there are no
  interaction-box bounds to clamp `MOUSE_SENSITIVITY`, so a bad value reads
  as sluggish or twitchy rather than unreachable. The dz sign convention
  (push away = cursor up) is a guess too, and flipping it means flipping it
  in both `mouse.py` and `mpx_mouse.py`.
- **The tray/HUD has never been driven by the real sensor** — only by fake
  hand data, since the Ultraleap tracking service isn't installed on this
  machine yet. The UI itself was smoke-tested live against a real X server
  (tray icon shows, HUD shows/auto-hides, all three bridge signals arrive,
  tray mode switching reaches `set_engage_mode`), but every frame behind it
  came from `tests/fakes.py`, so HUD legibility, auto-hide feel, and the
  cost of emitting three signals per frame at ~100 frames/s with a real hand
  in view are all unverified.
- **No smoothing/deadzone** on cursor movement yet — raw palm position maps
  straight to screen pixels every frame, and mouse mode passes raw per-frame
  deltas through with no filtering either.
- **Two hands both in pointer mode at once will fight over cursor position**
  (each hand gets its own `GestureInterpreter` and mode now, but there's only
  one OS cursor — whichever hand's frame is processed last each tick wins).
  Not an issue for the intended one-hand-mouses/one-hand-gestures use case.
- Confirmed working against the live sensor (connects, tracks, dispatches
  real mouse/media actions). `tests/` covers the gesture-logic state machine
  and config loading with fake hand data; nothing exercises the compiled
  bindings themselves in CI since that needs the physical sensor.

## Tests

```
pip install --user -r requirements-dev.txt
pytest
```
