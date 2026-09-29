"""Read-only cross-file check for the 2026-09-29 batch; not a scientific gate."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "test/script/reports"
EVIDENCE = REPORTS / "evidence"
SPEC = [
    ("6-0928", "V1", "2026-09-29_6-0928.md", "2026-09-29_6-0928_v2_final.json"),
    ("7-0928", "V2", "2026-09-29_7-0928_V2.md", "2026-09-29_7-0928_gate_v2_final.json"),
    ("8-0928", "V1", "2026-09-29_8-0928.md", "2026-09-29_8-0928_v2_final.json"),
    ("9-0928", "V1", "2026-09-29_9-0928.md", "2026-09-29_9-0928_v2_final.json"),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rule = ROOT / "test/script/README.md"
    goal = ROOT / "src/goal.md"
    rows = {}
    for line in goal.read_text(encoding="utf-8").splitlines():
        cells = line.split("|")
        if len(cells) > 11 and re.fullmatch(r"\d+-\d{4}", cells[1].strip()):
            rows[cells[1].strip()] = cells
    out = {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "File/hash/goal consistency only; semantic and scientific reviews are recorded in reports.",
        "rule_sha256": sha(rule), "goal_sha256": sha(goal),
        "order": [x[0] for x in SPEC], "checks": [],
    }
    for pid, version, report_name, evidence_name in SPEC:
        evidence = EVIDENCE / evidence_name
        e = json.loads(evidence.read_text(encoding="utf-8"))
        project = Path(e["project_dir"])
        report = REPORTS / report_name
        source = report.read_text(encoding="utf-8")
        g = rows[pid]
        assert e["rule_sha256"] == sha(rule) and sha(rule) in source, pid
        assert Path(g[7].strip()) == project and g[6].strip() == version, pid
        assert g[10].strip() == "待签署" and g[4].strip() == project.name, pid
        assert g[2].strip() in (project / "论文_中文.md").read_text(encoding="utf-8"), pid
        required = ["src.md", "speek.md", "final_prompt.md", "框架.md", "目标配置卡.md",
                    "文献核验.md", "P3_自检.md", "P4_审稿返修.md", "交付说明.md",
                    "论文_中文.md", "论文_英文.md", "论文_中文.docx", "论文_英文.docx"]
        for name in required:
            path = project / name
            assert path.is_file(), (pid, name)
            if name.startswith("论文_"):
                assert sha(path) in source, (pid, "report hash stale", name)
        for lang in ("中文", "英文"):
            d, m, pdf = e["docx"][lang], e["markdown"][lang], e["render_pdf"][lang]
            c = m["counts"]
            assert d["images"] == 3 and d["tables"] == 2 and d["footer_page_field"], pid
            assert d["zip_crc_bad_member"] is None, pid
            assert m["doi_unique_count"] == 10 and m["doi_count"] == 10, pid
            assert m["equations_sequential"] and len(m["equation_numbers"]) == 7, pid
            assert all(m["figure_paths_exist"].values()) and not m["contains_matlab_word"], pid
            assert c["main_figure_count"] == 3 and c["main_table_count"] == 2, pid
            assert c["reference_entry_count"] == 10, pid
            assert sha(Path(pdf["path"])) == pdf["sha256"] and pdf["sha256"] in source, pid
        for number in range(1, 4):
            f = e["figures"][f"图{number}"]
            assert f["fig"] and f["png"], pid
            for ext in ("fig", "png"):
                assert sha(project / "仿真/图" / f"图{number}.{ext}") == f[f"{ext}_sha256"], pid
        package = e["simulation_package"]
        assert package["zip_crc_bad_member"] is None and package["sha256"] in source, pid
        assert sha(project / "仿真/仿真打包.zip") == package["sha256"], pid
        if package["sha256_matches_sidecar"] is not None:
            assert package["sha256_matches_sidecar"], pid
        for link in re.findall(r"\]\((evidence/[^)]+)\)", source):
            assert (REPORTS / link).is_file(), link
        assert "FJH" in source and "待签署" in source, pid
        out["checks"].append({
            "id": pid, "version": version, "title": g[4].strip(), "authors": g[2].strip(),
            "status": "technical_review_complete_pending_FJH",
            "report": str(report), "report_sha256": sha(report),
            "evidence": str(evidence), "evidence_sha256": sha(evidence),
            "unresolved_technical_blocker": 0, "unresolved_technical_major": 0,
            "pdf_pages": {k: v["page_count"] for k, v in e["render_pdf"].items()},
        })
    pairs = {p.parent.resolve() for p in (ROOT / "gen").rglob("src.md")
             if (p.parent / "speek.md").is_file()}
    active = {Path(rows[pid][7].strip()).resolve() for pid, *_ in SPEC}
    seven = Path(rows["7-0928"][7].strip())
    historical = seven.parent.parent / "V1" / seven.name
    assert pairs == active | {historical.resolve()}, "New or unaccounted prompt project found"
    out["prompt_directory_pairs"] = sorted(str(p.relative_to(ROOT)) for p in pairs)
    out["historical_superseded"] = "7-0928/V1; original zero-positive data retained; active goal is V2."
    out["unprocessed_active_generation_tasks"] = 0
    out["pending_formal_signatures"] = 4
    out["checking_scripts_sha256"] = {
        str(p.relative_to(ROOT)): sha(p) for p in
        [Path(__file__), ROOT / "test/script/check_gate_evidence.py",
         ROOT / "test/script/check_reference_updates.py", ROOT / "test/script/check_v2_project7.py",
         ROOT / "test/script/check_v2_project8.py"]
    }
    destination = EVIDENCE / "2026-09-29_batch_final.json"
    destination.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: 4 reports, 8 bilingual MD/DOCX pairs, 8 PDF hashes, 12 FIG/PNG pairs, "
          "4 ZIPs, exact title/author goal mappings; 4 FJH signatures pending.")


if __name__ == "__main__":
    main()
