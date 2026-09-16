"""Linux pointer backend -- a virtual input device via `/dev/uinput`.

Why this exists: the existing X11/MPX backend injects through XTest, which
Wayland compositors deliberately do not honour. `uinput` sits *below* the
display server -- it creates a kernel-level virtual pointer that looks like
real hardware -- so it works on Wayland, on X11, and on a bare console alike.
That makes it the only Linux path that works on Matthew's own desktop
session, which is Wayland.

Pure `ctypes` + `struct` against the kernel ABI; no third-party package.

The tradeoff versus MPX
-----------------------
MPX gives each hand a genuinely independent OS cursor. uinput gives one
virtual device, hence one cursor -- `supports_multi_pointer = False`. Gaining
Wayland costs the two-cursor trick, so this is offered alongside MPX rather
than replacing it.

Permissions
-----------
`/dev/uinput` is root-only by default. The clean fix is a udev rule rather
than running the whole app as root:

    KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"

with the user added to the `input` group. The error raised below says this,
because "permission denied" with no remedy is the single most common reason
people give up on uinput.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
import struct
import time

from .base import PointerSink, clamp

# --- kernel ABI constants (linux/input-event-codes.h, linux/uinput.h) ------
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
ABS_X, ABS_Y = 0x00, 0x01
REL_X, REL_Y = 0x00, 0x01
EV_REL = 0x02

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

BUS_VIRTUAL = 0x06
ABS_MAX = 0x3F
ABS_CNT = ABS_MAX + 1

#: The absolute axis range we advertise. Using a fixed logical range and
#: scaling into it ourselves keeps behaviour identical regardless of the
#: actual screen resolution, and avoids re-creating the device if it changes.
ABS_RANGE = 65535

_BUTTON_CODES = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
# timeval is two longs (64-bit each on x86_64); the kernel fills them in when
# they are zero, so we always send zeros.
_EVENT = struct.Struct("llHHi")


def _screen_size():
    """Best-effort screen size, used to scale pixels into the abs range.

    Tries Xlib if it happens to be importable (it usually is on this project),
    then falls back to a sane default. Deliberately never fatal: a wrong size
    makes the cursor mapping wrong, not the backend unusable.
    """
    try:
        from Xlib import display as _display

        screen = _display.Display().screen()
        return int(screen.width_in_pixels), int(screen.height_in_pixels)
    except Exception:  # noqa: BLE001 - any failure just means "use the default"
        return 1920, 1080


class _UinputUserDev(ctypes.Structure):
    """struct uinput_user_dev, the legacy device-setup blob written to the fd.

    The modern alternative is UI_DEV_SETUP with struct uinput_setup, but the
    legacy write path works on every kernel this will meet and needs no
    version probing.
    """

    _fields_ = [
        ("name", ctypes.c_char * 80),
        ("id_bustype", ctypes.c_uint16),
        ("id_vendor", ctypes.c_uint16),
        ("id_product", ctypes.c_uint16),
        ("id_version", ctypes.c_uint16),
        ("ff_effects_max", ctypes.c_uint32),
        ("absmax", ctypes.c_int32 * ABS_CNT),
        ("absmin", ctypes.c_int32 * ABS_CNT),
        ("absfuzz", ctypes.c_int32 * ABS_CNT),
        ("absflat", ctypes.c_int32 * ABS_CNT),
    ]


class UinputPointer(PointerSink):
    """A kernel-level virtual pointer. Works under Wayland and X11."""

    name = "uinput"
    supports_multi_pointer = False

    def __init__(self, device_name="IntuiMotion Virtual Pointer", screen=None):
        try:
            self._fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        except PermissionError as error:
            raise PermissionError(
                "cannot open /dev/uinput. Add a udev rule:\n"
                '  KERNEL=="uinput", GROUP="input", MODE="0660", '
                'OPTIONS+="static_node=uinput"\n'
                "then add your user to the 'input' group and re-login."
            ) from error
        except FileNotFoundError as error:
            raise FileNotFoundError(
                "/dev/uinput is missing -- load the module with "
                "`sudo modprobe uinput`."
            ) from error

        self.width, self.height = screen or _screen_size()

        # Declare capabilities BEFORE creating the device; the kernel latches
        # them at UI_DEV_CREATE and ignores anything set afterwards.
        for ev in (EV_KEY, EV_ABS, EV_REL, EV_SYN):
            fcntl.ioctl(self._fd, UI_SET_EVBIT, ev)
        for code in _BUTTON_CODES.values():
            fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)
        for axis in (ABS_X, ABS_Y):
            fcntl.ioctl(self._fd, UI_SET_ABSBIT, axis)
        for axis in (REL_X, REL_Y):
            fcntl.ioctl(self._fd, UI_SET_RELBIT, axis)

        setup = _UinputUserDev()
        setup.name = device_name.encode()[:79]
        setup.id_bustype = BUS_VIRTUAL
        setup.id_vendor = 0x1209  # pid.codes, the open hardware VID
        setup.id_product = 0x0001
        setup.id_version = 1
        for axis in (ABS_X, ABS_Y):
            setup.absmin[axis] = 0
            setup.absmax[axis] = ABS_RANGE
        os.write(self._fd, bytes(setup))
        fcntl.ioctl(self._fd, UI_DEV_CREATE)

        # The compositor needs a moment to notice the new device; events sent
        # before it binds are silently dropped.
        time.sleep(0.2)

    def _emit(self, ev_type, code, value):
        os.write(self._fd, _EVENT.pack(0, 0, ev_type, code, int(value)))

    def _sync(self):
        self._emit(EV_SYN, SYN_REPORT, 0)

    def move_to(self, x, y):
        sx = clamp(int(x), 0, self.width - 1) * ABS_RANGE // max(1, self.width - 1)
        sy = clamp(int(y), 0, self.height - 1) * ABS_RANGE // max(1, self.height - 1)
        self._emit(EV_ABS, ABS_X, sx)
        self._emit(EV_ABS, ABS_Y, sy)
        self._sync()

    def move_by(self, dx, dy):
        self._emit(EV_REL, REL_X, int(round(dx)))
        self._emit(EV_REL, REL_Y, int(round(dy)))
        self._sync()

    def press(self, button="left"):
        self._emit(EV_KEY, _BUTTON_CODES.get(button, BTN_LEFT), 1)
        self._sync()

    def release(self, button="left"):
        self._emit(EV_KEY, _BUTTON_CODES.get(button, BTN_LEFT), 0)
        self._sync()

    def close(self):
        fd, self._fd = getattr(self, "_fd", None), None
        if fd is None:
            return
        try:
            fcntl.ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(fd)
