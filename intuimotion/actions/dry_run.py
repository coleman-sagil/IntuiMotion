import functools


class _State:
    enabled = False


_state = _State()


def is_enabled():
    return _state.enabled


def set_enabled(enabled):
    _state.enabled = enabled


def guarded(describe):
    """Decorator: while dry-run is enabled, print `describe(*args, **kwargs)`
    instead of calling the real function, so gesture changes can be tested
    without moving the real mouse, changing real volume, or running real
    shell commands.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if _state.enabled:
                print(f"[dry-run] {describe(*args, **kwargs)}")
                return None
            return func(*args, **kwargs)

        return wrapper

    return decorator
