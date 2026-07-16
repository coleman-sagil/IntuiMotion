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
```

Pointer-mode cursor movement bypasses the dispatcher and is wired directly in
`main.py`, since it's continuous per-frame motion rather than a discrete
triggered action.

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
| `palm_engage` | open, still hand held ~0.4s | enters pointer mode |
| `pinch` (idle) | thumb+index pinch while idle | play/pause |
| `left_press` / `left_release` (pointer mode) | thumb+index pinch start/end while in pointer mode | left mouse button down/up |
| `right_press` / `right_release` (pointer mode) | thumb+middle pinch start/end while in pointer mode | right mouse button down/up |
| `fist_exit` | fist held ~0.15s in pointer mode | exits pointer mode |
| `swipe_up` / `swipe_down` | fast vertical hand motion while idle | volume up / down |
| `swipe_right` / `swipe_left` | fast horizontal hand motion while idle | next / previous track |

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
- **No smoothing/deadzone** on cursor movement yet — raw palm position maps
  straight to screen pixels every frame.
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
