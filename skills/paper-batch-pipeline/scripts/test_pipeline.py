#!/usr/bin/env python3
"""Isolated smoke/integration tests. Never writes into the user's projects."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("pipeline.py")
spec = importlib.util.spec_from_file_location("pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="paper-pipeline-test-")
        self.root = Path(self.tmp.name)
        self.ws = self.root / "workspace"
        self.ws.mkdir()
        self.skill = self.root / "skill"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "references").mkdir()
        shutil.copy2(SCRIPT, self.skill / "scripts/pipeline.py")
        (self.skill / "references/master-prompt.md").write_text(
            "Workspace {{workspace}}\nProject {{project}}\nReview {{review}}\nGoal {{goal}}\nBatch {{batch_id}}\n", encoding="utf-8")
        self.project = self.make_project("p1/V1/测试论文")
        self.rule = self.write("test/README.md", "# Review\n研究稿可交付须全部门禁通过，并由 FJH 签署。\n")
        self.goal = self.write_goal()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text):
        path = self.ws / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def make_project(self, rel, title="测试论文", authors=""):
        p = self.ws / "gen/artifacts" / rel
        p.mkdir(parents=True, exist_ok=True)
        (p / "src.md").write_text(f"文章题目: {title}\n作者: {authors} #预留位\n", encoding="utf-8")
        (p / "speek.md").write_text("补充：真实实验、禁止假数据。\n", encoding="utf-8")
        (p / "仿真/图").mkdir(parents=True, exist_ok=True)
        return p

    def write_goal(self, extra="", bom=False):
        text = ("# Ledger\r\n\r\n| 稿件ID | auth | 标题 | 产物路径 | 进度 | note |\r\n"
                "| --- | --- | --- | --- | --- | --- |\r\n"
                f"| p1 | 作者甲，作者乙 | 测试论文 | {self.project} | 旧进度 | 保留\\|原样 |\r\n" + extra + "\r\n")
        goal = self.ws / "src/goal.md"
        goal.parent.mkdir(parents=True, exist_ok=True)
        goal.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return goal

    def call(self, command, *args, expected=0, parse=True):
        result = subprocess.run([sys.executable, str(self.skill / "scripts/pipeline.py"), command,
                                 "--workspace", str(self.ws), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr) if parse else result.stdout

    def state(self, project=None, progress="需重设计", complete_evidence=False):
        project = project or self.project
        state = {"schema_version": 1, "project_id": "p1", "title": "测试论文", "authors": ["作者甲", "作者乙"],
                 "phase": "preflight", "progress": progress, "reason": "single-class pilot cannot test the hypothesis"}
        if complete_evidence:
            self.call("compose", "--project", project, parse=False)
            state.update({"prompt_sha256": pipeline.sha256(project / "final_prompt.md"),
                          "inputs_sha256": {"src": pipeline.sha256(project / "src.md"), "speek": pipeline.sha256(project / "speek.md"), "review": pipeline.sha256(self.rule)},
                          "gates": {gate: "pass" for gate in pipeline.GATES}, "artifacts": [],
                          "signature": {"required": True, "signer": "", "evidence_path": "", "evidence_sha256": ""}})
            for role, extensions in pipeline.ROLES.items():
                stem = "paired-figure" if role in {"figure_fig", "figure_png"} else role
                artifact = project / "test-assets" / (stem + sorted(extensions)[0])
                artifact.parent.mkdir(exist_ok=True)
                artifact.write_text("Synthetic test fixture; not a scientific asset. " + role, encoding="utf-8")
                state["artifacts"].append({"path": str(artifact.relative_to(project)), "sha256": pipeline.sha256(artifact), "role": role})
            report = project / "review.md"
            report.write_text("Synthetic structural fixture; no scientific review asserted.", encoding="utf-8")
            state["review"] = {"path": "review.md", "sha256": pipeline.sha256(report), "rule_sha256": pipeline.sha256(self.rule),
                               "prompt_sha256": state["prompt_sha256"], "blocker_count": 0, "major_count": 0}
        self.save_state(project, state)
        return state

    def save_state(self, project, state):
        p = project / ".paper-pipeline/status.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_scan_logical_leaf_and_goal_inheritance(self):
        result = self.call("scan")
        self.assertEqual(result["project_count"], 1)
        item = result["projects"][0]
        self.assertEqual(item["authors_source"], "goal")
        self.assertEqual(item["authors"], ["作者甲", "作者乙"])
        self.assertTrue(item["goal_match"]["path_match"])
        self.assertEqual(result["signature_requirement"]["signer"], "FJH")

    def test_nested_prompt_parent_shadowed(self):
        self.make_project("p1/V1/测试论文/child", title="测试论文")
        result = self.call("scan")
        self.assertEqual(result["project_count"], 1)
        self.assertEqual(len(result["shadowed"]), 1)
        self.call("compose", "--project", self.project, expected=2)

    def test_all_versions_and_explicit_scope(self):
        self.make_project("p1/V2/测试论文")
        self.assertEqual(self.call("scan")["project_count"], 2)
        result = self.call("scan", "--scope", "goal-paths")
        self.assertEqual(result["project_count"], 1)
        self.assertEqual(len(result["excluded"]), 1)

    def test_conflicting_reviews_need_explicit_selection(self):
        self.write("test/script/README.md", "different rule\n")
        self.call("scan", expected=2)
        self.assertEqual(self.call("scan", "--review", "test/script/README.md")["project_count"], 1)

    def test_equal_reviews_ignore_bom_and_newline_only(self):
        p = self.ws / "test/script/README.md"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\xef\xbb\xbf" + self.rule.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(self.call("scan")["review"], str(self.rule))

    def test_goal_multiple_files_requires_explicit(self):
        shutil.copy2(self.goal, self.ws / "goal.md")
        self.call("scan", expected=2)
        self.assertEqual(self.call("scan", "--goal", "src/goal.md")["project_count"], 1)

    def test_prompt_author_conflict_does_not_inherit(self):
        (self.project / "src.md").write_text("文章题目: 测试论文\n作者: 其他作者\n", encoding="utf-8")
        self.assertEqual(self.call("scan")["projects"][0]["goal_match"]["status"], "unmatched")

    def test_empty_author_line_does_not_consume_next_parameter(self):
        (self.project / "src.md").write_text("文章题目: 测试论文\n作者:\n篇幅: 4500字\n", encoding="utf-8")
        self.assertEqual(self.call("scan")["projects"][0]["authors_source"], "goal")

    def test_compose_echo_noop_and_backup(self):
        output = self.call("compose", "--project", self.project, parse=False)
        final = self.project / "final_prompt.md"
        self.assertEqual(output, final.read_text(encoding="utf-8"))
        self.assertIn((self.project / "src.md").read_text(encoding="utf-8"), output)
        before = final.stat().st_mtime_ns
        self.call("compose", "--project", self.project, parse=False)
        self.assertEqual(before, final.stat().st_mtime_ns)
        (self.project / "speek.md").write_text("Updated supplement\n", encoding="utf-8")
        self.call("compose", "--project", self.project, parse=False)
        backups = list((self.project / ".paper-pipeline/history").glob("final_prompt.*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), output)

    def test_dry_run_then_apply_preserves_bom_crlf_other_cells(self):
        self.goal = self.write_goal(bom=True)
        self.state()
        before = self.goal.read_bytes()
        result = self.call("update-goal")
        self.assertFalse(result["written"])
        self.assertEqual(before, self.goal.read_bytes())
        result = self.call("update-goal", "--apply")
        self.assertTrue(result["written"])
        self.assertEqual(self.goal.read_bytes(), before.replace("旧进度".encode(), "需重设计".encode()))
        self.assertEqual(Path(result["backup"]).read_bytes(), before)

    def test_versions_aggregate_worst_and_missing_state_skips(self):
        v2 = self.make_project("p1/V2/测试论文")
        self.state(progress="执行中")
        result = self.call("update-goal")
        self.assertEqual(len(result["skipped"]), 1)
        self.state(v2, progress="阻断")
        self.assertEqual(self.call("update-goal")["changes"][0]["to"], "阻断")

    def test_identity_mismatch_skips_entire_row(self):
        state = self.state()
        state["authors"] = ["其他人"]
        self.save_state(self.project, state)
        result = self.call("update-goal", "--apply")
        self.assertFalse(result["written"])
        self.assertEqual(len(result["skipped"]), 1)

    def test_conflicting_version_cannot_be_hidden_by_matching_version(self):
        self.state(progress="执行中")
        self.make_project("p1/V2/测试论文", authors="其他作者")
        result = self.call("update-goal", "--apply")
        self.assertFalse(result["written"])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(len(result["unresolved"]), 1)

    def test_awaiting_signature_accepts_complete_structure(self):
        self.state(progress="待签署", complete_evidence=True)
        result = self.call("update-goal")
        self.assertEqual(result["changes"][0]["to"], "待签署")
        self.assertEqual(result["changes"][0]["projects"][0]["errors"], [])

    def test_completion_requires_rule_signer_and_hash(self):
        state = self.state(progress="已完成", complete_evidence=True)
        self.assertEqual(self.call("update-goal")["changes"][0]["to"], "阻断")
        signature = self.project / "signature.md"
        signature.write_text("Structural fixture; not an actual signature.", encoding="utf-8")
        state["signature"].update({"signer": "FJH", "evidence_path": "signature.md", "evidence_sha256": pipeline.sha256(signature)})
        self.save_state(self.project, state)
        self.assertEqual(self.call("update-goal")["changes"][0]["to"], "已完成")
        state["signature"]["required"] = False
        self.save_state(self.project, state)
        self.assertEqual(self.call("update-goal")["changes"][0]["to"], "阻断")

    def test_stale_data_and_stale_rule_refuse_completed(self):
        state = self.state(progress="待签署", complete_evidence=True)
        (self.project / state["artifacts"][0]["path"]).write_text("changed", encoding="utf-8")
        self.assertEqual(self.call("update-goal")["changes"][0]["to"], "阻断")
        self.rule.write_text("New review requires FJH.\n", encoding="utf-8")
        errors = self.call("update-goal")["changes"][0]["projects"][0]["errors"]
        self.assertTrue(any("rules hash" in value for value in errors))

    def test_unpassed_gate_and_missing_matlab_assets_block(self):
        state = self.state(progress="待签署", complete_evidence=True)
        state["gates"]["independent_v2"] = "pending"
        state["artifacts"] = [a for a in state["artifacts"] if a["role"] != "figure_fig"]
        self.save_state(self.project, state)
        errors = self.call("update-goal")["changes"][0]["projects"][0]["errors"]
        self.assertTrue(any("independent_v2" in value for value in errors))
        self.assertTrue(any("figure_fig" in value for value in errors))

    def test_empty_asset_and_unpaired_figures_block(self):
        state = self.state(progress="待签署", complete_evidence=True)
        asset = state["artifacts"][0]
        path = self.project / asset["path"]
        path.write_bytes(b"")
        asset["sha256"] = pipeline.sha256(path)
        png = next(a for a in state["artifacts"] if a["role"] == "figure_png")
        path = self.project / png["path"]
        changed = path.with_name("different-stem.png")
        path.rename(changed)
        png["path"] = str(changed.relative_to(self.project))
        self.save_state(self.project, state)
        errors = self.call("update-goal")["changes"][0]["projects"][0]["errors"]
        self.assertTrue(any("empty" in value for value in errors))
        self.assertTrue(any("same-stem" in value for value in errors))

    def test_symlink_project_ignored_when_platform_permits(self):
        target = self.root / "external"
        target.mkdir()
        (target / "src.md").write_text("outside", encoding="utf-8")
        (target / "speek.md").write_text("outside", encoding="utf-8")
        link = self.ws / "gen/artifacts/link"
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            self.skipTest("Platform does not permit creating symlinks without additional privileges")
        result = self.call("scan")
        self.assertEqual(result["project_count"], 1)
        self.assertTrue(any(i["reason"] == "symlink_or_junction" for i in result["ignored"]))
        self.call("compose", "--project", link, expected=2)

    def test_snapshot_cannot_overwrite_existing(self):
        before = self.goal.read_bytes()
        self.call("scan", "--output", self.goal, expected=2)
        self.assertEqual(self.goal.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
