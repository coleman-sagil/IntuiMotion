import shlex
import subprocess

from pynput.keyboard import Controller as KeyboardController, Key

_keyboard = KeyboardController()

_KEY_ALIASES = {
    "ctrl": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "cmd": Key.cmd,
    "super": Key.cmd,
    "enter": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc,
    "space": Key.space,
}


def _resolve_key(name):
    return _KEY_ALIASES.get(name.lower(), name)


def run_keys(keys):
    resolved = [_resolve_key(k) for k in keys]
    pressed = []
    try:
        for key in resolved:
            _keyboard.press(key)
            pressed.append(key)
    finally:
        for key in reversed(pressed):
            _keyboard.release(key)


def run_shell(command):
    # shlex.split + no shell=True: config-file commands run as a literal
    # argv, not through a shell, so no injection risk from config content.
    subprocess.Popen(shlex.split(command))
