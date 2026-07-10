from pynput.keyboard import Controller as KeyboardController, Key

from .dry_run import guarded

_keyboard = KeyboardController()


@guarded(lambda: "volume up")
def volume_up():
    _keyboard.tap(Key.media_volume_up)


@guarded(lambda: "volume down")
def volume_down():
    _keyboard.tap(Key.media_volume_down)


@guarded(lambda: "mute")
def mute():
    _keyboard.tap(Key.media_volume_mute)


@guarded(lambda: "play/pause")
def play_pause():
    _keyboard.tap(Key.media_play_pause)


@guarded(lambda: "next track")
def next_track():
    _keyboard.tap(Key.media_next)


@guarded(lambda: "previous track")
def previous_track():
    _keyboard.tap(Key.media_previous)
