from __future__ import annotations

import re
import unittest

from paradox_mod_merger_tool.parse import iter_object_blocks


class ParseTests(unittest.TestCase):
    def test_iter_object_blocks_keeps_leading_comments(self) -> None:
        object_start_re = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*{\s*$", re.MULTILINE)
        text = "# comment\nexample_object = {\n\tvalue = 1\n}\n"
        results = iter_object_blocks(text, object_start_re)
        self.assertEqual(results[0][0], "example_object")
        self.assertTrue(results[0][1].startswith("# comment"))


if __name__ == "__main__":
    unittest.main()
