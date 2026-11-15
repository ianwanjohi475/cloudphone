"""Unit tests for the parts of the server that do not need a phone.

    python3 -m unittest discover tests
"""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import app  # noqa: E402


class ControlMessages(unittest.TestCase):
    """Sizes and fields must match scrcpy 2.x's control protocol exactly."""

    def test_touch(self):
        msg = app.pack_touch(app.ACTION_DOWN, 3, 100, 200, 720, 1600)
        self.assertEqual(len(msg), 32)
        kind, action, pointer, x, y, w, h, pressure = struct.unpack(">BBqiiHHH", msg[:24])
        self.assertEqual((kind, action, pointer, x, y, w, h), (2, 0, 3, 100, 200, 720, 1600))
        self.assertEqual(pressure, 0xFFFF)
        self.assertEqual(app.pack_touch(app.ACTION_UP, 0, 1, 1, 2, 2)[22:24], b"\x00\x00")

    def test_key_text_scroll(self):
        self.assertEqual(app.pack_key(app.ACTION_DOWN, 66), bytes([0, 0, 0, 0, 0, 66]) + bytes(8))
        self.assertEqual(app.pack_text("hé"), b"\x01\x00\x00\x00\x03h\xc3\xa9")
        scroll = app.pack_scroll(10, 20, 720, 1600, 0, -1)
        self.assertEqual(len(scroll), 21)
        self.assertEqual(struct.unpack(">hh", scroll[13:17]), (0, -0x8000))


class SafeName(unittest.TestCase):
    def test_names(self):
        self.assertEqual(app.safe_name("My Report (final).pdf"), "My Report (final).pdf")
        self.assertEqual(app.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(app.safe_name("C:\\Users\\ian\\clip.mp4"), "clip.mp4")
        self.assertEqual(app.safe_name("a;rm -rf $HOME`x`.txt"), "a_rm -rf _HOME_x_.txt")
        self.assertEqual(app.safe_name("видео.mp4"), "видео.mp4")
        self.assertEqual(app.safe_name("..."), "file")
        self.assertLessEqual(len(app.safe_name("x" * 500 + ".mp4")), 112)


class PickApks(unittest.TestCase):
    ABIS = ["x86_64", "arm64-v8a"]

    def test_keeps_only_the_preferred_cpu_split(self):
        names = ["base.apk", "split_config.arm64_v8a.apk", "split_config.x86_64.apk",
                 "split_config.xxhdpi.apk", "split_config.en.apk"]  # fmt: skip
        self.assertEqual(
            sorted(app.pick_apks(names, self.ABIS)),
            ["base.apk", "split_config.en.apk", "split_config.x86_64.apk", "split_config.xxhdpi.apk"],
        )

    def test_arm_only_bundle_uses_translation(self):
        names = ["base.apk", "config.arm64_v8a.apk", "config.armeabi_v7a.apk"]
        self.assertEqual(app.pick_apks(names, self.ABIS), ["base.apk", "config.arm64_v8a.apk"])

    def test_no_cpu_splits(self):
        self.assertEqual(app.pick_apks(["a.apk", "b.apk"], self.ABIS), ["a.apk", "b.apk"])

    def test_unusable_bundle(self):
        with self.assertRaises(ValueError):
            app.pick_apks(["base.apk", "config.armeabi_v7a.apk"], ["x86_64"])


if __name__ == "__main__":
    unittest.main()
