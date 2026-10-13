import unittest

from ctal.canon import CanonError, canonical_bytes, digest_obj, parse_strict


class CanonTests(unittest.TestCase):
    def test_deterministic_sorted_no_whitespace(self):
        self.assertEqual(canonical_bytes({"b": 1, "a": [True, None, "x"]}), b'{"a":[true,null,"x"],"b":1}')
        self.assertEqual(canonical_bytes({"a": 1, "b": 2}), canonical_bytes({"b": 2, "a": 1}))

    def test_utf16_key_order(self):
        # U+FF5E sorts after U+10000 by UTF-16 code units (RFC 8785), unlike code point order
        o = {"～": 1, "\U00010000": 2}
        self.assertTrue(canonical_bytes(o).decode().index("\U00010000") < canonical_bytes(o).decode().index("～"))

    def test_rejects_ambiguous_inputs(self):
        for bad, code in [({"a": 1.5}, "FLOAT_NOT_ALLOWED"), ({"a": 2 ** 60}, "INT_OUT_OF_RANGE"),
                          ({"a": "é"}, "NON_NFC_STRING"), ({"a": "\ud800"}, "LONE_SURROGATE"),
                          ({1: "x"}, "NON_STRING_KEY"), ({"a": object()}, "UNSUPPORTED_TYPE")]:
            with self.assertRaises(CanonError) as cm:
                canonical_bytes(bad)
            self.assertEqual(cm.exception.code, code)

    def test_parse_strict_rejections(self):
        cases = {b'{"a":1,"a":2}': "DUPLICATE_KEY", b'{"a":1.0}': "FLOAT_NOT_ALLOWED", b'{"a":NaN}': "FLOAT_NOT_ALLOWED",
                 b'\xef\xbb\xbf{}': "BOM_NOT_ALLOWED", b'\xff': "INVALID_UTF8", b'{': "MALFORMED_JSON",
                 b'[' * 5000 + b']' * 5000: "TOO_DEEP", b'[' * 40 + b']' * 40: "TOO_DEEP"}
        for data, code in cases.items():
            with self.assertRaises(CanonError, msg=data[:20]) as cm:
                parse_strict(data)
            self.assertEqual(cm.exception.code, code, data[:20])
        with self.assertRaises(CanonError):
            parse_strict(b'{"a":"' + b"x" * 100 + b'"}', max_bytes=50)

    def test_digest_stable(self):
        self.assertEqual(digest_obj({"a": 1}), "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862")


if __name__ == "__main__":
    unittest.main()
