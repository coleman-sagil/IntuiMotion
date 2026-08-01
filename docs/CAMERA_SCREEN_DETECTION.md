# Camera-based screen detection

`intuimotion/camera.py` + `intuimotion/screen_detector.py`, merged in from
the standalone `DeepLens-VT` prototype (2026-08-01) once the plan changed
from two machines (a dedicated AWS DeepLens SoC talking to the IntuiMotion
box over the network) to one machine (any UVC-compliant webcam on the same
box IntuiMotion already runs on). The AWS DeepLens hardware itself was
never actually used for anything in the ported code — DeepLens-VT bypassed
AWS's end-of-lifed DeepLens service entirely and talked to a plain V4L2/
OpenCV camera, so nothing about it depended on that specific hardware.

## What's here

- **`camera.py`** — `Camera` wraps `cv2.VideoCapture`. Raises `CameraError`
  cleanly on failure. Not yet run against a real camera on this machine —
  validated so far only against synthetic frames and mocked `cv2` calls
  (see `tests/test_camera.py`).
- **`screen_detector.py`** — `ScreenDetector.detect(frame)` finds the
  largest 4-sided bright rectangular region in a camera frame (OpenCV
  contour + `approxPolyDP`, no trained model) and returns its 4 corners in
  camera-pixel space, labeled `top_left`/`top_right`/`bottom_right`/
  `bottom_left` — the same canonical order `calibration.py` and
  `boundary_calibration.py` already use for Leap-space corners. Needs
  real-world validation: a synthetic test frame has none of the glare,
  competing bright rectangles, or uneven lighting a real room does.

## What was deliberately left out of the merge

DeepLens-VT also had `inference.py` (a generic `InferenceEngine`/
`MotionDetector` placeholder), `transport.py` (a `Publisher` abstraction
for sending results across the network to a second machine), and a
`pipeline.py`/`main.py` wiring those three into a standalone
camera→inference→publish loop. None of that was ported:

- `transport.py` existed specifically to cross the network gap between two
  machines. That gap no longer exists once the camera is local to
  IntuiMotion, so a `Publisher`/network layer here would be dead code
  representing an architecture that isn't being built.
- `inference.py`'s `MotionDetector` was an explicit placeholder "until
  [what to detect] is decided" — DeepLens-VT's own blueprint already
  resolved that question in favor of screen detection, so the generic
  placeholder doesn't add anything `screen_detector.py` doesn't already
  do more specifically.
- `pipeline.py`/`main.py` only existed to run the now-dropped
  inference/transport duo as a standalone program; camera + screen
  detection are now just importable modules inside IntuiMotion instead.

## What's genuinely still open (not built here)

Turning "a camera can find a screen's corners in pixel space" into "point/
gesture at that real screen and control it like a touchscreen" needs a
coordinate-fusion step that has never been built in either repo: a
homography from the camera's pixel-space screen corners to the same
Leap-space plane `calibration.py`/`boundary_calibration.py` already
calibrate against, likely via a one-time calibration pass (point at each
detected corner with a tracked hand). This project's own norm is that new
features get discussed before being built, not bug fixes — so this file
records the idea without implementing it. Whoever picks this up next should
treat it as a design conversation first.
