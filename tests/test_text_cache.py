import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "firmware"))
from text_cache import FRAME_BYTES, HEADER_BYTES, load_cache, save_cache


class TextCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temporary.name) / "中文.txt.e6cache")
        self.key = hashlib.sha256(b"inputs").digest()
        self.frame = bytearray(b"\x35\x62" * (FRAME_BYTES // 2))
        self.checksum = hashlib.sha256(self.frame).digest()

    def tearDown(self):
        self.temporary.cleanup()

    def test_cache_roundtrip_reuses_buffer_and_replaces_file(self):
        save_cache(self.path, self.key, self.checksum, self.frame)
        target = bytearray(FRAME_BYTES)
        frame, checksum = load_cache(self.path, self.key, target)
        self.assertIs(frame, target)
        self.assertEqual(frame, self.frame)
        self.assertEqual(checksum, self.checksum.hex())
        self.frame[0] = 0x01
        checksum = hashlib.sha256(self.frame).digest()
        save_cache(self.path, self.key, checksum, self.frame)
        self.assertEqual(load_cache(self.path, self.key, target)[0], self.frame)
        self.assertFalse(Path(self.path + ".tmp").exists())

    def test_wrong_key_truncation_extra_bytes_and_bad_header_are_misses(self):
        save_cache(self.path, self.key, self.checksum, self.frame)
        self.assertIsNone(load_cache(self.path, b"z" * 32))
        original = Path(self.path).read_bytes()
        for data in (b"", original[:HEADER_BYTES - 1], original[:-1], original + b"z",
                     b"WRNG" + original[4:], original[:4] + struct.pack("<H", 400) + original[6:]):
            Path(self.path).write_bytes(data)
            self.assertIsNone(load_cache(self.path, self.key))

    def test_failed_replacement_is_a_miss_and_cleans_temporary_file(self):
        save_cache(self.path, self.key, self.checksum, self.frame)
        with patch("text_cache.os.rename", side_effect=OSError("power interrupted")):
            with self.assertRaises(OSError):
                save_cache(self.path, self.key, self.checksum, self.frame)
        self.assertIsNone(load_cache(self.path, self.key))
        self.assertFalse(Path(self.path + ".tmp").exists())
