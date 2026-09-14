"""OpenMotion source -- frames from our own driver, no vendor SDK.

This speaks directly to the OpenMotion driver binary (`openleap stream`),
which is our own reverse-engineered libusb driver for the original Leap
Motion Controller. It replaces the Ultraleap/LeapC path entirely: no vendor
daemon, no vendor CDN, no proprietary runtime.

Wire protocol (defined by `rust-driver/src/lib.rs::run_stream`)
---------------------------------------------------------------
stdout, repeating, little-endian::

    b"LFRM"            4 bytes  magic
    <frame counter>    4 bytes  uint32 LE
    <pixels>           307200 bytes, 1280x240 8-bit gray,
                                left/right eyes column-interleaved

stderr carries human-readable diagnostics. stdin accepts line commands::

    exp <microseconds>     fixed exposure (also disables auto-exposure)
    ae <0|1>               auto-exposure off/on
    leds <0-7>             IR LED bitmask (bit0 left, bit1 centre, bit2 right)

Two layers, deliberately separate
---------------------------------
`OpenMotionSource` owns *transport* only -- spawn the driver, parse frames,
manage the process lifecycle. Turning an IR image pair into hand joints is a
separate concern (`pose_solver`), because that stage is modality-specific:
a stereo-IR rig, a depth camera, a LiDAR and a radar frontend all produce
different raw data but must emit the same `Hand` objects. Keeping the split
here is what lets a future sensor reuse everything above this line.

Current status: the driver has an unresolved bulk-transfer regression and
streams zero frames (see OpenMotion `reverse-engineering/FINDINGS.md`). The
transport below is correct and ready; until that regression is fixed this
source will report "no frames" rather than silently appearing to work. Use
the `synthetic` source to exercise the UI in the meantime.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import threading
import time

from .base import HandSource

MAGIC = b"LFRM"
EYE_WIDTH = 640
FRAME_HEIGHT = 240
INTERLEAVED_WIDTH = EYE_WIDTH * 2
FRAME_BYTES = INTERLEAVED_WIDTH * FRAME_HEIGHT  # 307200
HEADER = struct.Struct("<4sI")

#: Seconds to wait for the first frame before declaring the driver silent.
FIRST_FRAME_TIMEOUT = 8.0


def default_binary():
    """Locate the driver binary.

    Env var wins so a packaged build, a USB-stick deployment, or a Windows
    install can point at wherever it actually shipped the executable.
    """
    from_env = os.environ.get("OPENMOTION_BINARY")
    if from_env:
        return from_env
    on_path = shutil.which("openleap") or shutil.which("openmotion")
    if on_path:
        return on_path
    # Development layout: IntuiMotion and OpenMotion side by side.
    here = os.path.dirname(os.path.abspath(__file__))
    guess = os.path.join(
        here, "..", "..", "..", "OpenMotion", "rust-driver", "target", "debug", "openleap"
    )
    return os.path.normpath(guess)


def default_sequence():
    from_env = os.environ.get("OPENMOTION_SEQUENCE")
    if from_env:
        return from_env
    binary = default_binary()
    # bringup_seq.txt sits at the driver crate root, two levels above target/debug.
    crate_root = os.path.normpath(os.path.join(os.path.dirname(binary), "..", ".."))
    return os.path.join(crate_root, "bringup_seq.txt")


class OpenMotionSource(HandSource):
    """Streams IR frames from the OpenMotion driver and emits `Hand` objects.

    `pose_solver` is any callable taking the raw interleaved frame bytes and
    returning a list of `Hand`. Injecting it (rather than importing a solver
    here) keeps this module free of numpy/ONNX and keeps the transport
    testable on its own.
    """

    name = "openmotion"

    def __init__(
        self,
        on_hand_frame,
        on_tracking_frame=None,
        binary=None,
        sequence=None,
        pose_solver=None,
        use_pkexec=None,
        leds=0b101,
    ):
        super().__init__(on_hand_frame, on_tracking_frame)
        self.binary = binary or default_binary()
        self.sequence = sequence or default_sequence()
        self.pose_solver = pose_solver
        # The driver claims the USB device directly, which needs root on
        # Linux. Default to pkexec only when we are not already root.
        if use_pkexec is None:
            use_pkexec = os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() != 0
        self.use_pkexec = use_pkexec
        self.leds = leds
        self._process = None
        self._stderr_thread = None
        self.frames_seen = 0

    # -- lifecycle --------------------------------------------------------
    def _command(self):
        cmd = [self.binary, "stream", self.sequence]
        if self.use_pkexec:
            cmd = ["pkexec"] + cmd
        return cmd

    def _startup(self):
        if not os.path.exists(self.binary):
            raise FileNotFoundError(
                f"OpenMotion driver binary not found at {self.binary!r}. "
                "Build it with `cargo build` in OpenMotion/rust-driver, or set "
                "OPENMOTION_BINARY to its path."
            )
        cmd = self._command()
        print(f"[source:openmotion] launching: {' '.join(cmd)}")
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )
        self._stderr_thread = threading.Thread(
            target=self._pump_stderr, name="openmotion-stderr", daemon=True
        )
        self._stderr_thread.start()

    def _pump_stderr(self):
        """Driver diagnostics are genuinely useful (bring-up counts, frame
        tearing, timeouts) -- surface them rather than swallowing them."""
        stream = self._process.stderr if self._process else None
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                print(f"[openmotion] {line}")

    def send_command(self, command):
        """Send a control line to the running driver (`exp`, `ae`, `leds`)."""
        proc = self._process
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write((command.rstrip() + "\n").encode())
            proc.stdin.flush()
            return True
        except (BrokenPipeError, ValueError):
            return False

    def _shutdown(self):
        proc, self._process = self._process, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass

    # -- transport --------------------------------------------------------
    def _read_exactly(self, count):
        """Read exactly `count` bytes, or None if the stream ended/stopped.

        A plain `read(n)` on a pipe is free to return fewer bytes than asked;
        at 307KB per frame that happens constantly, so short reads must be
        accumulated or every frame would be misaligned.
        """
        stream = self._process.stdout
        chunks = []
        remaining = count
        while remaining > 0 and not self.stopped:
            chunk = stream.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks) if remaining == 0 else None

    def _resync(self):
        """Scan forward to the next MAGIC. Guards against a partial write or a
        stderr/stdout interleaving hiccup desynchronising the stream."""
        window = b""
        while not self.stopped:
            byte = self._process.stdout.read(1)
            if not byte:
                return False
            window = (window + byte)[-4:]
            if window == MAGIC:
                return True
        return False

    def _produce(self):
        self.send_command(f"leds {self.leds}")
        deadline = time.monotonic() + FIRST_FRAME_TIMEOUT
        while not self.stopped:
            header = self._read_exactly(HEADER.size)
            if header is None:
                break
            magic, counter = HEADER.unpack(header)
            if magic != MAGIC:
                if not self._resync():
                    break
                counter = -1
                rest = self._read_exactly(4)
                if rest is None:
                    break
                counter = struct.unpack("<I", rest)[0]
            payload = self._read_exactly(FRAME_BYTES)
            if payload is None:
                break
            self.frames_seen += 1
            if self.pose_solver is None:
                # Transport works, but nothing can turn pixels into joints.
                # Say so once, clearly, instead of emitting empty frames
                # forever and looking like a tracking failure.
                if self.frames_seen == 1:
                    print(
                        "[source:openmotion] receiving frames "
                        f"({INTERLEAVED_WIDTH}x{FRAME_HEIGHT}) but no pose_solver "
                        "is configured, so no hands will be emitted."
                    )
                continue
            hands = self.pose_solver(payload, counter) or []
            self.emit(hands)

        if self.frames_seen == 0 and not self.stopped:
            waited = max(0.0, FIRST_FRAME_TIMEOUT - (deadline - time.monotonic()))
            print(
                f"[source:openmotion] driver produced 0 frames after {waited:.1f}s. "
                "This is the known bulk-transfer regression -- see OpenMotion "
                "reverse-engineering/FINDINGS.md. Run with "
                "INTUIMOTION_SOURCE=synthetic to exercise the UI meanwhile."
            )
