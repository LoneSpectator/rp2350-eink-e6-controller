"""Persist final TXT pixels beside the source, with input and payload hashes."""
import binascii
import hashlib
import os
import struct
import sign_log as log

from content import HEIGHT, WIDTH, exact_read, render_file
from timing import report, ticks_ms

HEADER = "<4sHHI32s32s"
HEADER_BYTES = 76
FRAME_BYTES = WIDTH * HEIGHT // 2


def load_cache(path, key, buffer=None):
    try:
        with open(path, "rb") as stream:
            magic, width, height, length, inputs, checksum = struct.unpack(
                HEADER, exact_read(stream, HEADER_BYTES))
            if (magic != b"E6C1" or width != WIDTH or height != HEIGHT or
                    length != FRAME_BYTES or inputs != key or
                    os.stat(path)[6] != HEADER_BYTES + FRAME_BYTES):
                return None
            frame = buffer if buffer is not None else bytearray(FRAME_BYTES)
            if len(frame) != FRAME_BYTES:
                raise ValueError("incorrect reusable frame length")
            view = memoryview(frame)
            digest = hashlib.sha256()
            for offset in range(0, length, 4096):
                chunk = view[offset:offset + 4096]
                if stream.readinto(chunk) != len(chunk):
                    return None
                digest.update(chunk)
            if digest.digest() != checksum:
                return None
            return frame, binascii.hexlify(checksum).decode()
    except (OSError, ValueError):
        return None


def save_cache(path, key, checksum, frame):
    temporary = path + ".tmp"
    try:
        with open(temporary, "wb") as stream:
            stream.write(struct.pack(HEADER, b"E6C1", WIDTH, HEIGHT, len(frame), key, checksum))
            view = memoryview(frame)
            for offset in range(0, len(frame), 4096):
                stream.write(view[offset:offset + 4096])
        if hasattr(os, "sync"):
            os.sync()
        # FAT does not portably support rename over an existing file. A lost
        # cache after interrupted replacement is safe: the TXT is regenerated.
        try:
            os.remove(path)
        except OSError as exc:
            if not exc.args or exc.args[0] != 2:
                raise
        os.rename(temporary, path)
        if hasattr(os, "sync"):
            os.sync()
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def text_frame(path, font_path, settings, rotation, inputs, buffer=None):
    key = binascii.unhexlify(inputs)
    cached = load_cache(path + ".e6cache", key, buffer)
    if cached is not None:
        log.debug("Text cache hit:", path)
        return cached
    log.info("Text cache rebuild:", path)
    started = ticks_ms()
    frame = render_file(path, font_path, settings, rotation, buffer)
    report("text_render", started)
    checksum = hashlib.sha256(frame).digest()
    try:
        save_cache(path + ".e6cache", key, checksum, frame)
    except OSError as exc:
        # Caching is an optimization; a full/read-only card must not prevent
        # displaying the freshly rendered text.
        log.warning("Text cache write failed:", exc)
    return frame, binascii.hexlify(checksum).decode()
