import re
import subprocess

from pynput.mouse import Button, Controller as MouseController

_mouse = MouseController()


def _detect_screen_size():
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


def _clamp(value, low, high):
    return max(low, min(high, value))


def map_to_screen(leap_x, leap_y):
    x_norm = (leap_x - LEAP_X_RANGE[0]) / (LEAP_X_RANGE[1] - LEAP_X_RANGE[0])
    y_norm = (leap_y - LEAP_Y_RANGE[0]) / (LEAP_Y_RANGE[1] - LEAP_Y_RANGE[0])
    screen_x = _clamp(x_norm, 0.0, 1.0) * SCREEN_WIDTH
    screen_y = (1.0 - _clamp(y_norm, 0.0, 1.0)) * SCREEN_HEIGHT
    return screen_x, screen_y


def move_to(x, y):
    _mouse.position = (int(x), int(y))


def move_to_leap_position(leap_x, leap_y):
    move_to(*map_to_screen(leap_x, leap_y))


def click(button="left"):
    _mouse.click(Button.right if button == "right" else Button.left)


def press(button="left"):
    _mouse.press(Button.right if button == "right" else Button.left)


def release(button="left"):
    _mouse.release(Button.right if button == "right" else Button.left)
