from pynput.keyboard import Controller as KeyboardController, Key

_keyboard = KeyboardController()


def volume_up():
    _keyboard.tap(Key.media_volume_up)


def volume_down():
    _keyboard.tap(Key.media_volume_down)


def mute():
    _keyboard.tap(Key.media_volume_mute)


def play_pause():
    _keyboard.tap(Key.media_play_pause)


def next_track():
    _keyboard.tap(Key.media_next)


def previous_track():
    _keyboard.tap(Key.media_previous)
