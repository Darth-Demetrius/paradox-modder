from __future__ import annotations

import re
import unittest

from paradox_mod_merger_tool.parse import iter_object_blocks, split_leading_file_variable_definitions


class ParseTests(unittest.TestCase):
    def test_iter_object_blocks_keeps_leading_comments(self) -> None:
        object_start_re = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*{\s*$", re.MULTILINE)
        text = "# comment\nexample_object = {\n\tvalue = 1\n}\n"
        results = iter_object_blocks(text, object_start_re)
        self.assertEqual(results[0][0], "example_object")
        self.assertTrue(results[0][1].startswith("# comment"))

    def test_split_leading_file_variable_definitions_drops_only_comments_before_future_variables(self) -> None:
        text = """
        # generated merge note
        @city_cost = 500
        # EPM: Hive/Plant organic empires cost
        @city_hive_food_cost = 167
        # keep: this comment is after the last variable

        district_city = {
            minerals = @city_cost
        }
        """.strip()

        definitions, remainder = split_leading_file_variable_definitions(text)

        self.assertEqual(definitions["@city_cost"], "@city_cost = 500")
        self.assertEqual(definitions["@city_hive_food_cost"], "@city_hive_food_cost = 167")
        self.assertNotIn("# generated merge note", remainder)
        self.assertNotIn("# EPM: Hive/Plant organic empires cost", remainder)
        self.assertIn("# keep: this comment is after the last variable", remainder)
        self.assertIn("district_city = {", remainder)
        self.assertNotIn("@city_cost = 500", remainder)


if __name__ == "__main__":
    unittest.main()
