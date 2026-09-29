#!/usr/bin/env python3
"""Run the bundled pilot and ledger workflow in a NEW isolated directory."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New directory; existing paths are refused.")
    args = parser.parse_args()
    root = Path(args.output).absolute()
    if root.exists() or root.is_symlink():
        parser.error(f"Output already exists; use a new isolated directory: {root}")
    skill = Path(__file__).resolve().parent.parent
    shutil.copytree(skill / "assets/example-workspace", root)
    pipeline = skill / "scripts/pipeline.py"

    def command(*argv, cwd=root):
        completed = subprocess.run([sys.executable, str(pipeline), *argv, "--workspace", str(root)],
                                   cwd=cwd, text=True, encoding="utf-8", capture_output=True, check=True)
        return completed.stdout

    scan = json.loads(command("scan"))
    write_json(root / "scan.json", scan)
    if scan["project_count"] != 1 or scan["projects"][0]["goal_match"]["status"] != "matched":
        raise RuntimeError("Bundled example no longer resolves to exactly one matched project.")
    item = scan["projects"][0]
    project = Path(item["path"])
    prompt = command("compose", "--project", str(project))
    # Emit the entire final prompt before any experimental calculation.
    sys.stdout.write(prompt)
    sys.stdout.flush()
    pilot_run = subprocess.run([sys.executable, "preflight.py"], cwd=project,
                               text=True, encoding="utf-8", capture_output=True, check=True)
    pilot = json.loads(pilot_run.stdout)
    (project / "先导/run.log").write_text(pilot_run.stdout + pilot_run.stderr, encoding="utf-8")
    if pilot["event_proxy_count"] != 0:
        raise RuntimeError("The pilot changed; reassess its scientific decision instead of reusing the demo diagnosis.")
    diagnosis = f"""# 先导核验与重设计记录

## 本次真实运行

- 数据：明确为合成演练参数，种子{pilot['seed']}，{pilot['cases']}个工况，40秒窗口、0.02秒采样。
- 完整极滑代理事件：{pilot['event_proxy_count']}；未触及代理阈值：{pilot['no_event_proxy_count']}。
- 最大采样幅值：{pilot['max_sampled_amplitude_rad']:.9f} rad。
- 最大能量幅值上界：{pilot['max_energy_bound_rad']:.9f} rad，远低于2π。
- 原始逐工况数据在`先导/pilot.csv`；统计在`先导/pilot.json`；公式在`preflight.py`。

## 判定：需重设计

正阻尼线性振子加小扰动会使能量非增，且没有故障干预、非线性失步或场站耦合机制。这组实验不能检验标题期望的稳定/失稳识别。有限窗口未触阈值不等于真实系统稳定证明；不能把不存在的失稳标签补造出来，也不能报告一个平凡的100%分类精度。

模型阶数低本身不是否决依据。本案例失败在于题目需要的现象被模型与参数预先排除，故实验与目标不匹配。没有进行算法对比，也没有得到有效方法贡献。

## 下一版设计提案（尚未执行）

1. 明确研究对象、决策时点、可观测信息、预测时限和有物理依据的稳定/未判定标准。
2. 对同步调相机应用建立能保留必要非线性、电网耦合、励磁及故障切除行为的模型；明确同步调相机机械有功输入假设，核验故障前后可行平衡。参数来源需核实，本案例数值不能作为工程依据。
3. 在求解标签前冻结有依据的工况域和纳入规则；检验事件覆盖与现实性，保留失败及未判定样本，不按算法输赢筛选。
4. 对照容量裕度、清除时间、清除状态、无注意力模型和完整模型；所有方法信息和调参预算相称。预先给出具有应用依据的主指标、有效收益阈值及误报/漏报约束，本演练不编造数值门槛。
5. 按独立物理族划分开发与保留测试；先导仅供设计。若看过测试后再改方案，使用新独立测试并披露尝试。
6. 若方法不满足核心有效性判据，继续分析根因与重设计；最多3轮后真实阻断。不得把负结果改称方法有效。
7. 设计及实验通过后，实际运行MATLAB，保留原始MAT/CSV、入口和参数、FIG/PNG、环境和日志、ZIP，再成文、独立复算、审稿并等待指定守门人签署。

## 未执行范围

上述新设计、算法验证、MATLAB、论文终稿和签署均未执行。演练进度为“需重设计”。
"""
    (project / "重设计记录.md").write_text(diagnosis, encoding="utf-8")
    state_dir = project / ".paper-pipeline"
    state_dir.mkdir(exist_ok=True)
    state = {
        "schema_version": 1, "project_id": item["project_id"], "title": item["title"],
        "authors": item["authors"], "phase": "preflight", "progress": "需重设计",
        "prompt_sha256": digest(project / "final_prompt.md"), "inputs_sha256": item["inputs_sha256"],
        "gates": {"design": "fail", "experiment": "fail", "independent_v2": "pending",
                  "manuscript": "pending", "matlab_assets": "pending", "review": "pending"},
        "artifacts": [{"path": path, "sha256": digest(project / path), "role": role}
                      for path, role in [("先导/pilot.csv", "pilot_data"), ("先导/pilot.json", "pilot_metrics"),
                                         ("重设计记录.md", "redesign_record"), ("preflight.py", "pilot_source")]],
        "review": {}, "signature": {"required": True, "signer": "", "evidence_path": "", "evidence_sha256": ""},
        "reason": "60个先导工况均无极滑代理事件，模型排除了待预测现象，需重设计。",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    write_json(state_dir / "status.json", state)
    ledger = Path(scan["goal"])
    original = ledger.read_bytes()
    preview = json.loads(command("update-goal"))
    write_json(root / "update-preview.json", preview)
    if len(preview["changes"]) != 1 or preview["changes"][0]["to"] != "需重设计":
        raise RuntimeError("Preview does not match the pilot diagnosis; do not apply.")
    applied = json.loads(command("update-goal", "--apply"))
    write_json(root / "update-applied.json", applied)
    expected = original.replace("| 待处理 |".encode(), "| 需重设计 |".encode(), 1)
    if ledger.read_bytes() != expected or not applied["written"]:
        raise RuntimeError("Example ledger changed outside the expected progress cell.")
    result = {"workspace": str(root), "project": str(project), "progress": "需重设计", "pilot": pilot,
              "ledger_only_progress_changed": True, "matlab_executed": False, "manuscript_delivered": False}
    write_json(root / "demo-result.json", result)
    print("\n# 演练结果\n" + json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
