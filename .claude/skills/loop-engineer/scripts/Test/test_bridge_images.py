import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Put the parent folder of the test folder (scripts) on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import bridge_images


class TestBridgeImages(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_file(self, name: str, content: bytes) -> Path:
        path = self.tmp_dir / name
        path.write_bytes(content)
        return path

    def test_none_and_empty_list_leave_the_body_byte_identical(self):
        payload = {"text": "hello"}
        original_json = json.dumps(payload)

        result_none = bridge_images.attach_images(payload, None, 1024)
        self.assertEqual(json.dumps(result_none), original_json)
        self.assertNotIn("images", result_none)

        result_empty = bridge_images.attach_images(payload, [], 1024)
        self.assertEqual(json.dumps(result_empty), original_json)
        self.assertNotIn("images", result_empty)

    def test_images_are_base64_of_the_file_bytes_in_order(self):
        file1 = self._write_file("img1.png", b"img1bytes")
        file2 = self._write_file("img2.png", b"img2bytes")
        
        payload = {"text": "look"}
        result = bridge_images.attach_images(payload, [file1, file2], 1024)
        
        self.assertIn("images", result)
        expected_b64_1 = base64.b64encode(b"img1bytes").decode("ascii")
        expected_b64_2 = base64.b64encode(b"img2bytes").decode("ascii")
        
        self.assertEqual(result["images"], [expected_b64_1, expected_b64_2])

    def test_the_argument_is_not_mutated(self):
        file1 = self._write_file("img1.png", b"data")
        payload = {"text": "hello"}
        original_payload = dict(payload)
        
        bridge_images.attach_images(payload, [file1], 1024)
        
        self.assertEqual(payload, original_payload)
        self.assertNotIn("images", payload)

    def test_missing_file_raises_and_names_the_position(self):
        missing_file = self.tmp_dir / "missing.png"
        with self.assertRaises(bridge_images.ImageError) as ctx:
            bridge_images.encode_images([missing_file], 1024)
        
        self.assertIn("1", str(ctx.exception))
        self.assertIn("missing", str(ctx.exception).lower())

    def test_oversized_file_raises(self):
        file1 = self._write_file("big.png", b"x" * 2048)
        with self.assertRaises(bridge_images.ImageError) as ctx:
            bridge_images.encode_images([file1], 1024)
        
        self.assertIn("1", str(ctx.exception))
        self.assertIn("larger", str(ctx.exception).lower())

    def test_empty_file_raises(self):
        file1 = self._write_file("empty.png", b"")
        with self.assertRaises(bridge_images.ImageError) as ctx:
            bridge_images.encode_images([file1], 1024)
        
        self.assertIn("1", str(ctx.exception))
        self.assertIn("empty", str(ctx.exception).lower())

    def test_message_never_holds_the_path(self):
        file1 = self._write_file("secret_path.png", b"data")
        try:
            bridge_images.encode_images([file1], 1) # Force oversized to trigger error
        except bridge_images.ImageError as e:
            self.assertNotIn("secret_path.png", str(e))
            self.assertNotIn(str(file1), str(e))
        else:
            self.fail("Expected ImageError")

    def test_attach_images_with_error_propagates(self):
        missing_file = self.tmp_dir / "missing.png"
        payload = {"text": "hello"}
        with self.assertRaises(bridge_images.ImageError):
            bridge_images.attach_images(payload, [missing_file], 1024)


if __name__ == "__main__":
    unittest.main()
