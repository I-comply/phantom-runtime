import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atl.graph import CapabilityGraph, GraphError

TOOLS = {"fs_read": {}, "hash_text": {}, "echo": {}, "fs_write": {}}
DOC = {"threshold": 0.5, "edges": [
    {"from": "fs_read", "to": "hash_text", "weight": 0.9, "tokens": ["hash", "checksum"]},
    {"from": "hash_text", "to": "echo", "weight": 0.8},
    {"from": "fs_read", "to": "fs_write", "weight": 0.9, "tokens": ["copy", "write"]},
]}


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.g = CapabilityGraph(TOOLS, DOC)

    def test_valid_plan(self):
        self.assertIsNone(self.g.validate_plan(["fs_read", "hash_text", "echo"], "hash the file"))

    def test_rejects_hallucinated(self):
        self.assertEqual(self.g.validate_plan(["fs_read", "rm_rf"], "x"), "unknown_node:rm_rf")
        self.assertEqual(self.g.validate_plan(["echo", "fs_read"], "x"), "no_edge:echo->fs_read")
        self.assertEqual(self.g.validate_plan(["fs_read", "fs_write"], "hash the file"), "low_score:fs_read->fs_write")
        self.assertEqual(self.g.validate_plan([], "x"), "empty_plan")

    def test_route(self):
        self.assertEqual(self.g.route("fs_read", "hash checksum"), ["fs_read", "hash_text", "echo"])
        self.assertEqual(self.g.route("fs_read", "copy write"), ["fs_read", "fs_write"])
        self.assertEqual(self.g.route("fs_read", "unrelated"), ["fs_read"])

    def test_fail_closed(self):
        with self.assertRaises(GraphError):
            CapabilityGraph(TOOLS, {"edges": [{"from": "a", "to": "echo"}]})
        with self.assertRaises(GraphError):
            CapabilityGraph(TOOLS, {"edges": [{"from": "echo", "to": "fs_read"}, {"from": "fs_read", "to": "echo"}]})
        with self.assertRaises(GraphError):
            CapabilityGraph(TOOLS, {"edges": [{"from": "echo", "to": "fs_read", "weight": 2}]})


if __name__ == "__main__":
    unittest.main()
