from pynput.mouse import Button, Controller as MouseController

_mouse = MouseController()

try:
    import tkinter

    _root = tkinter.Tk()
    _root.withdraw()
    SCREEN_WIDTH = _root.winfo_screenwidth()
    SCREEN_HEIGHT = _root.winfo_screenheight()
    _root.destroy()
except Exception:
    SCREEN_WIDTH, SCREEN_HEIGHT = 1920, 1080

# Leap "interaction box" bounds in millimeters, roughly centered above the
# sensor -- untuned guesses, adjust against your own sensor placement.
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
