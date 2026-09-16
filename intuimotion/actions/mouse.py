import re
import subprocess

from pynput.mouse import Button, Controller as MouseController

from ..sinks.screen import native_screen_size
from .dry_run import guarded

_mouse = MouseController()


def _detect_screen_size():
    # Platform-native query first (Windows virtual desktop, macOS main
    # display, or an explicit $INTUIMOTION_SCREEN override). Without this,
    # non-Linux hosts fell straight through to the 1920x1080 default and the
    # pointer mapping was silently wrong on any other resolution -- the
    # cursor still moved, it just landed in the wrong place, with no error.
    # Returns None on Linux, so the xrandr path below stays authoritative
    # there.
    native = native_screen_size()
    if native:
        return native

    # xrandr's "current WxH" is the full X11 root window / RandR virtual
    # desktop size -- the same coordinate space pynput's Controller.position
    # moves in, spanning every monitor, not just one. tkinter's
    # winfo_screenwidth() was tried here before and silently reported a
    # single-monitor size (or wasn't even installed), which is why pointer
    # mode couldn't reach a second monitor.
    try:
        output = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, check=True, timeout=2
        ).stdout
        match = re.search(r"current (\d+) x (\d+)", output)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:
        pass
    return 1920, 1080


SCREEN_WIDTH, SCREEN_HEIGHT = _detect_screen_size()

# Leap "interaction box" bounds in millimeters, roughly centered above the
# sensor -- untuned guesses, adjust against your own sensor placement. Note
# this same mm range now maps across the full multi-monitor width, so
# horizontal sensitivity is higher than a single-monitor mapping would be --
# part of the tuning pass, not fixed here.
LEAP_X_RANGE = (-150.0, 150.0)
LEAP_Y_RANGE = (100.0, 400.0)

# Screen pixels per Leap millimeter of *relative* hand motion, for
# Mode.MOUSE's touchpad-style movement. Same status as LEAP_X_RANGE/
# LEAP_Y_RANGE above: an untuned starting point, picked to feel roughly like
# a mid-sensitivity touchpad and never checked against real hand data. Needs
# a tuning pass on real hardware -- and unlike the absolute mapping, this one
# has no interaction-box bounds to clamp it, so a bad value just makes the
# cursor feel sluggish or twitchy rather than unreachable.
MOUSE_SENSITIVITY = 4.0


def _clamp(value, low, high):
    return max(low, min(high, value))


def map_to_screen(leap_x, leap_y):
    x_norm = (leap_x - LEAP_X_RANGE[0]) / (LEAP_X_RANGE[1] - LEAP_X_RANGE[0])
    y_norm = (leap_y - LEAP_Y_RANGE[0]) / (LEAP_Y_RANGE[1] - LEAP_Y_RANGE[0])
    screen_x = _clamp(x_norm, 0.0, 1.0) * SCREEN_WIDTH
    screen_y = (1.0 - _clamp(y_norm, 0.0, 1.0)) * SCREEN_HEIGHT
    return screen_x, screen_y


@guarded(lambda x, y: f"move cursor to ({int(x)}, {int(y)})")
def move_to(x, y):
    _mouse.position = (int(x), int(y))


def move_to_leap_position(leap_x, leap_y):
    move_to(*map_to_screen(leap_x, leap_y))


@guarded(lambda dx, dy: f"move cursor by ({int(round(dx))}, {int(round(dy))})")
def move_by(dx, dy):
    # pynput's Controller.move() is a *relative* move -- it reads .position
    # and adds the offsets -- unlike assigning .position, which is absolute
    # (confirmed against the installed pynput's Controller.move source, not
    # just its docstring). Rounding rather than truncating so small
    # per-frame deltas don't all bias toward zero and stall the cursor.
    _mouse.move(int(round(dx)), int(round(dy)))


def move_by_leap_delta(dx_mm, dz_mm):
    """Mode.MOUSE counterpart to move_to_leap_position.

    Consumes GestureInterpreter's `pointer_delta`: one frame's (dx, dz)
    change in hand position along the desk plane, in Leap millimeters,
    already clutch-gated by the interpreter. All this layer does is scale mm
    to pixels and pick the axis signs, the same split as the absolute
    pointer_position/map_to_screen pair above.
    """
    # Sign convention -- a first guess, easy to flip during real-hardware
    # tuning, same status as everything else in this file's mapping layer:
    # Leap's +z increases *toward* the user, so pushing the hand away from
    # you yields a negative dz, and passing it straight through yields a
    # negative screen dy, i.e. the cursor moves up. Push away = up, pull
    # back = down, which is how a physical touchpad behaves. If it comes out
    # inverted on the real sensor, flip the sign on the dz term below -- and
    # on the identical line in mpx_mouse.move_by_leap_delta, which mirrors
    # this convention so both cursor paths behave the same.
    move_by(dx_mm * MOUSE_SENSITIVITY, dz_mm * MOUSE_SENSITIVITY)


@guarded(lambda button="left": f"{button} click")
def click(button="left"):
    _mouse.click(Button.right if button == "right" else Button.left)


@guarded(lambda button="left": f"{button} button down")
def press(button="left"):
    _mouse.press(Button.right if button == "right" else Button.left)


@guarded(lambda button="left": f"{button} button up")
def release(button="left"):
    _mouse.release(Button.right if button == "right" else Button.left)
