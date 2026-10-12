"""Offline regression tests: python -m unittest discover -s test/script -p test_manuscript_config.py."""
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generate_src as generate
import watch_src as watch


class ManuscriptConfigTests(unittest.TestCase):
    def test_blank_rows_are_not_manuscripts(self):
        table = "| 稿件ID | 状态 | 标题 | type | 进度 |\n| --- | --- | --- | --- | --- |\n"
        table += "| a | V1 | 题目 | 科技核心 | |\n| | | | | |\n| | |\n"
        self.assertEqual(len(list(generate.table_rows(table))), 1)

    def test_malformed_nonempty_rows_report_line(self):
        header = "| 稿件ID | 状态 | 标题 | type | 进度 |\n| --- | --- | --- | --- | --- |\n"
        for bad in ("| 整条记录误放一个单元格 | | | | |", "| a | V1 | 题目 |"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "第 3 行"):
                list(generate.table_rows(header + bad))

    def test_order_type_alias_and_unit_boundaries(self):
        for label in ("类型", "类别"):
            values, titles = watch.parse_manuscripts(
                f"科核写作1篇\n部门：宝鸡 采编：Anny 订单时间：2026.9.24\n"
                f"{label}：科技核心 作者：鲁总 单位：中国电建集团西北勘测设计研究院有限公司\n"
                "题目：基于高斯泼溅与BIM融合的水利枢纽三维数字孪生场景动态重构算法")
            self.assertEqual(values["类别"], "科技核心")
            self.assertEqual(values["作者"], "鲁总")
            self.assertEqual(len(titles), 1)

    def test_four_profiles_in_generated_parameters(self):
        template = generate.TEMPLATE.read_text(encoding="utf-8")
        for category, language, length, figures, refs in (
            ("EI 会议", "中英双稿", "4000–4500", "恰好 5", "恰好 10"),
            ("普刊", "中文稿", "5000–8000", "3–6", "至少 10"),
            ("科技核心", "中文稿", "6000–6500", "图 3–8、表 2–6", "12–18"),
            ("SCI", "英文稿", "4000–6000", "4–8", "30–60"),
        ):
            with self.subTest(category=category):
                result = generate.replace_parameters(template, "测试题目", category)
                block = result.split("```yaml", 1)[1].split("```", 1)[0]
                for expected in (language, length, figures, refs):
                    self.assertIn(expected, block)
                self.assertNotIn("硬上限 4500", result)
                self.assertNotIn("≤ 4000字", result)

    def test_aliases_and_unknown_types(self):
        self.assertEqual(generate.manuscript_category("科核"), "中文科技核心")
        self.assertEqual(generate.manuscript_category("指定普刊：某刊"), "中文普刊")
        for value in ("", "只写不发", "未知类型"):
            with self.assertRaises(ValueError):
                generate.manuscript_parameters(value)

    def test_order_to_ledger_to_scaffold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            goal = root / "goal.md"
            goal.write_text("| 稿件ID | auth | type | 标题 | 状态 | 进度 | src |\n"
                            "| --- | --- | --- | --- | --- | --- | --- |\n", encoding="utf-8")
            order = root / "order.txt"
            parsed = watch.parse_manuscripts("订单时间：2026.9.24\n类型：科技核心\n作者：鲁总\n题目：测试题目")
            with patch.object(watch, "GOAL", goal), patch.object(generate, "GOAL", goal), patch.object(generate, "OUTPUT", root / "out"):
                watch.add_goal_rows(order, parsed, dt.date(2026, 10, 12))
                with goal.open("a", encoding="utf-8") as stream:
                    stream.write("| | | | | | | |\n")
                generate.main()
                generated = root / "out" / "order-1012" / "V1" / "测试题目"
                self.assertIn("6000–6500", (generated / "src.md").read_text(encoding="utf-8"))
                self.assertEqual((generated / "README.md").read_bytes(), generate.README_MD.read_bytes())
                self.assertIn("进行中", goal.read_text(encoding="utf-8"))
                (generated / "src.md").write_text("existing work", encoding="utf-8")
                generate.main()
                self.assertEqual((generated / "src.md").read_text(), "existing work")


if __name__ == "__main__":
    unittest.main()
