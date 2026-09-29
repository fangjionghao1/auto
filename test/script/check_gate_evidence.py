"""Collect reproducible, read-only evidence for one manuscript gate review.

This script checks file/package structure and identifiers. V1 prose, V2 scientific
claims, V3 topic fit, V4 publication judgement, and author declarations still
require a human reviewer under README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

try:
    from pypdf import PdfReader
except ImportError:  # Keep the rest of the evidence usable without this dependency.
    PdfReader = None


M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
HAN = re.compile(r"[\u4e00-\u9fff]")
ENGLISH_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*(?![A-Za-z0-9])")
BODY_START = re.compile(r"^##\s+1(?:[.、]?\s+)(?:引言|Introduction)(?:\s|$)", re.IGNORECASE)
REFERENCE_START = re.compile(r"^##\s+(?:参考文献|References|Bibliography)\s*$", re.IGNORECASE)
APPENDIX_START = re.compile(r"^##\s+(?:附录|补充材料|Appendix|Supplementary(?: Materials?)?)(?:\s|$)", re.IGNORECASE)
CAPTION = re.compile(r"^(?:\*\*)?\s*(?:(?:图|表)\s*\d+(?:[.：:、]?\s+|[.：:、])|(?:Figure|Table)\s*\d+\s*[.：:])", re.IGNORECASE)
SIMULATION_SUFFIXES = {".csv", ".mat", ".m", ".py", ".zip", ".json", ".txt", ".sha256"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {"sha256": sha256(path), "bytes": path.stat().st_size}


def visible_markdown(lines: list[str]) -> str:
    """Approximate visible prose; exclude TeX and image source/alt paths."""
    text = "\n".join(line for line in lines if not line.lstrip().startswith("!["))
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
    text = re.sub(r"\\\[.*?\\\]", "", text, flags=re.DOTALL)
    text = re.sub(r"\\begin\{(?:equation|align|gather)[^}]*\}.*?\\end\{(?:equation|align|gather)[^}]*\}",
                  "", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\\)\$(?!\$).*?(?<!\\)\$", "", text, flags=re.DOTALL)
    text = re.sub(r"!?\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)
    return text


def count_words(text: str, language: str) -> int:
    return len(HAN.findall(text) if language == "中文" else ENGLISH_WORD.findall(text))


def count_markdown_tables(lines: list[str]) -> int:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines + [""]:
        if line.lstrip().startswith("|"):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    return sum(any(re.fullmatch(r"[|:\-\s]+", line) and "-" in line for line in group)
               for group in groups)


def manuscript_counts(source: str, language: str) -> dict:
    lines = source.splitlines()
    start = next((index for index, line in enumerate(lines) if BODY_START.match(line)), None)
    reference = next((index for index, line in enumerate(lines) if REFERENCE_START.match(line)), None)
    appendix = next((index for index, line in enumerate(lines) if APPENDIX_START.match(line)), None)
    end_candidates = [index for index in (reference, appendix) if index is not None
                      and (start is None or index > start)]
    end = min(end_candidates) if end_candidates else len(lines)
    body_source = lines[start:end] if start is not None else []
    body_prose = [line for line in body_source
                  if line.strip() and not line.lstrip().startswith(("#", "|", "!["))
                  and not CAPTION.match(line.strip())]
    whole_visible = visible_markdown(lines)
    body_visible = visible_markdown(body_prose)
    main_figure_lines = body_source
    supplementary_lines = (lines[appendix:reference] if appendix is not None and
                           (reference is None or appendix < reference) else
                           (lines[appendix:] if appendix is not None else []))
    reference_lines = lines[reference + 1:] if reference is not None else []
    reference_entries = [line for line in reference_lines
                         if re.match(r"^\s*(?:\[\d+\]|\d+[.)])\s+", line)]
    unit = "Han characters" if language == "中文" else "English lexical tokens"
    return {
        "unit": unit,
        "tool": "check_gate_evidence.py regex count on Markdown UTF-8 source",
        "whole_manuscript_count": count_words(whole_visible, language),
        "body_net_count": count_words(body_visible, language) if start is not None else None,
        "body_start_line": start + 1 if start is not None else None,
        "body_end_line_exclusive": end + 1 if start is not None else None,
        "references_heading_line": reference + 1 if reference is not None else None,
        "appendix_heading_line": appendix + 1 if appendix is not None else None,
        "main_figure_count": sum(line.lstrip().startswith("![") for line in main_figure_lines),
        "main_table_count": count_markdown_tables(main_figure_lines),
        "supplementary_figure_count": sum(line.lstrip().startswith("![") for line in supplementary_lines),
        "supplementary_table_count": count_markdown_tables(supplementary_lines),
        "reference_entry_count": len(reference_entries) if reference is not None else None,
        "body_exclusions": ["title and front matter", "abstract", "section headings",
                            "figure and table captions", "image alt text and paths",
                            "Markdown table cells", "references", "appendix/supplementary material",
                            "display and inline TeX math"],
        "whole_manuscript_scope": "All visible Markdown text, including title, abstract, captions, "
                                  "table cells and references; TeX math and image alt/path excluded.",
        "caution": "Automated planning count; target venue/template word-count convention must be checked separately.",
    }


def inspect_docx(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        xml = ET.fromstring(archive.read("word/document.xml"))
        footers = [archive.read(name).decode("utf-8") for name in archive.namelist()
                   if name.startswith("word/footer") and name.endswith(".xml")]
        math = list(xml.iter(M + "oMath"))
        return {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "zip_crc_bad_member": bad_member,
            "omml_objects": len(math),
            "display_equations": sum(1 for _ in xml.iter(M + "oMathPara")),
            "empty_math_objects": sum(1 for obj in math if not "".join(obj.itertext()).strip()),
            "images": sum(1 for _ in xml.iter(A + "blip")),
            "tables": sum(1 for _ in xml.iter(W + "tbl")),
            "footer_page_field": any("PAGE" in footer for footer in footers),
        }


def inspect_render_pdf(project: Path, language: str, docx: Path) -> dict:
    filename = f"论文_{language}.pdf"
    # The final render normally lives below 排版核验/论文_<language>_<timestamp>/.
    candidates = list(project.rglob(filename))
    if not candidates:
        return {"status": "missing", "search_scope": str(project.resolve()),
                "filename": filename, "candidate_count": 0,
                "selection_basis": "No matching PDF in this project; no page count or PDF hash available."}

    def render_stamp(path: Path) -> int | None:
        match = re.fullmatch(rf"论文_{language}_(\d{{8}})_(\d{{6}})", path.parent.name)
        return int("".join(match.groups())) if match else None

    stamped = [path for path in candidates if render_stamp(path) is not None]
    if stamped:
        selected = max(stamped, key=lambda path: (render_stamp(path), path.stat().st_mtime_ns,
                                                   str(path)))
        basis = "Largest YYYYMMDD_HHMMSS stamp in matching render-folder name; file mtime breaks ties."
    else:
        selected = max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))
        basis = "No timestamped render folder; latest PDF file modification time."
    record = {
        "status": "found", "path": str(selected.resolve()), "filename": filename,
        "candidate_count": len(candidates), "selection_basis": basis,
        "render_folder_stamp": render_stamp(selected),
        "modified_at": datetime.fromtimestamp(selected.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "sha256": sha256(selected), "bytes": selected.stat().st_size,
        "docx_modified_at": (datetime.fromtimestamp(docx.stat().st_mtime).astimezone().isoformat(timespec="seconds")
                             if docx.is_file() else None),
        "render_not_older_than_docx": selected.stat().st_mtime_ns >= docx.stat().st_mtime_ns
                                      if docx.is_file() else None,
    }
    if PdfReader is None:
        record["page_count"] = None
        record["page_count_error"] = "pypdf is unavailable"
    else:
        try:
            record["page_count"] = len(PdfReader(str(selected)).pages)
            record["page_count_tool"] = "pypdf.PdfReader"
        except Exception as error:
            record["page_count"] = None
            record["page_count_error"] = f"{type(error).__name__}: {error}"
    return record


def asset_manifest(project: Path) -> dict:
    images = {}
    for path in sorted(project.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".fig", ".png"}:
            relative = path.relative_to(project).as_posix()
            images[relative] = {**file_record(path),
                                "publication_figure": path.parent.name == "图" and
                                path.parent.parent.name == "仿真"}
    simulation = {}
    simulation_root = project / "仿真"
    if simulation_root.is_dir():
        for path in sorted(simulation_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in SIMULATION_SUFFIXES:
                simulation[path.relative_to(project).as_posix()] = file_record(path)
    return {"figure_and_png_assets": images, "simulation_data_source_and_packages": simulation,
            "figure_and_png_count": len(images), "simulation_file_count": len(simulation)}


def target_configuration_card(project: Path) -> dict:
    project_id = next((parent.name for parent in project.parents
                       if re.fullmatch(r"\d+-\d{4}", parent.name)), None)
    goal = next((parent / "src" / "goal.md" for parent in project.parents
                 if (parent / "src" / "goal.md").is_file()), None)
    declared = {}
    if goal is not None and project_id:
        for line in goal.read_text(encoding="utf-8").splitlines():
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) > 11 and cells[1] == project_id:
                declared = {"authors_in_goal": cells[2], "category_in_goal": cells[3],
                            "title_in_goal": cells[4], "progress_in_goal": cells[10],
                            "goal_path": str(goal.resolve()), "goal_sha256": sha256(goal)}
                break
    return {
        "project_id": project_id, "declared_goal_metadata": declared or None,
        "venue_name": None, "manuscript_type": None,
        "official_guideline_url": None, "template_url": None, "guideline_checked_at": None,
        "page_limit": None, "word_or_character_limit": None, "venue_count_scope": None,
        "figure_table_requirement": None, "reference_requirement": None,
        "blind_review_requirement": None, "language_requirement": None,
        "declaration_requirement": None, "revision_file_requirement": None,
        "decision_letter_requirement": None,
        "manual_review_required": "Null fields must be filled from the named venue and article type; "
                                  "goal metadata is a declaration, not venue verification.",
    }


def related_review_evidence(project: Path, rule: Path) -> dict:
    card = project / "目标配置卡.md"
    project_id = next((parent.name for parent in project.parents
                       if re.fullmatch(r"\d+-\d{4}", parent.name)), None)
    evidence_dir = rule.parent / "reports" / "evidence"
    references = (sorted(evidence_dir.glob(f"*_{project_id}*_references.json"),
                         key=lambda path: (path.stat().st_mtime_ns, str(path)))
                  if project_id and evidence_dir.is_dir() else [])
    # A project's older version may have different references. Bind the exact
    # source directory recorded by the reference checker, not only its ID.
    matched = []
    for candidate in references:
        try:
            source_project = json.loads(candidate.read_text(encoding="utf-8")).get("project")
            if source_project and Path(source_project).resolve() == project.resolve():
                matched.append(candidate)
        except (ValueError, OSError):
            continue
    references = matched
    latest = references[-1] if references else None
    return {
        "target_configuration_file": ({"path": str(card.resolve()), **file_record(card)}
                                      if card.is_file() else None),
        "reference_verification_file": ({"path": str(latest.resolve()), **file_record(latest),
                                         "selection_basis": "Latest modified matching project references JSON"}
                                        if latest is not None else None),
    }


def inspect_markdown(path: Path, language: str) -> dict:
    source = path.read_text(encoding="utf-8")
    numbered = [int(value) for value in re.findall(r"\\tag\{(\d+)\}", source)]
    figure_paths = re.findall(r"!\[[^]]*\]\(([^)]+)\)", source)
    dois = re.findall(r"(?i)\b10\.\d{4,9}/[^\s<>)]+", source)
    dois = [doi.rstrip(".,;。") for doi in dois]
    return {
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "title": next((line.removeprefix("# ").strip() for line in source.splitlines()
                       if line.startswith("# ")), ""),
        "equation_numbers": numbered,
        "equations_sequential": numbered == list(range(1, len(numbered) + 1)),
        "figure_paths": figure_paths,
        "figure_paths_exist": {name: (path.parent / name).is_file() for name in figure_paths},
        "doi_count": len(dois),
        "doi_unique_count": len(set(dois)),
        "contains_matlab_word": "MATLAB" in source.upper(),
        "source_line_count": len(source.splitlines()),
        "counts": manuscript_counts(source, language),
    }


def inspect_package(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        members = archive.namelist()
    sidecar = next((candidate for candidate in
                    (path.with_suffix(".sha256"), path.with_suffix(".sha256.txt"))
                    + (Path(str(path) + ".sha256"), Path(str(path) + ".sha256.txt"))
                    if candidate.is_file()), None)
    recorded = (sidecar.read_text(encoding="utf-8").strip().split()[0]
                if sidecar is not None else None)
    actual = sha256(path)
    return {
        "sha256": actual,
        "bytes": path.stat().st_size,
        "members": len(members),
        "zip_crc_bad_member": bad_member,
        "sha256_sidecar_path": str(sidecar) if sidecar is not None else None,
        "sha256_sidecar": recorded,
        "sha256_matches_sidecar": recorded.lower() == actual.lower() if recorded else None,
    }


def collect(project: Path, rule: Path) -> dict:
    rule_text = rule.read_text(encoding="utf-8")
    record: dict = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_dir": str(project.resolve()),
        "rule_path": str(rule.resolve()),
        "rule_sha256": sha256(rule),
        "rule_version_heading": rule_text.splitlines()[0] if rule_text.splitlines() else None,
        "target_configuration_card": target_configuration_card(project),
        "related_review_evidence": related_review_evidence(project, rule),
        "files": {},
        "markdown": {},
        "docx": {},
        "render_pdf": {},
        "figures": {},
    }
    for name in ("final_prompt.md", "框架.md", "P3_自检.md", "P4_审稿返修.md",
                 "目标配置卡.md",
                 "交付说明.md", "文献核验.md", "论文_中文.md", "论文_英文.md",
                 "论文_中文.docx", "论文_英文.docx"):
        path = project / name
        record["files"][name] = file_record(path) if path.is_file() else None
    for language in ("中文", "英文"):
        md = project / f"论文_{language}.md"
        docx = project / f"论文_{language}.docx"
        if md.is_file():
            record["markdown"][language] = inspect_markdown(md, language)
        if docx.is_file():
            record["docx"][language] = inspect_docx(docx)
        record["render_pdf"][language] = inspect_render_pdf(project, language, docx)
    figure_dir = project / "仿真" / "图"
    if figure_dir.is_dir():
        stems = sorted({path.stem for path in figure_dir.glob("*.fig")}
                       | {path.stem for path in figure_dir.glob("*.png")})
        for stem in stems:
            record["figures"][stem] = {
                "fig": (figure_dir / f"{stem}.fig").is_file(),
                "png": (figure_dir / f"{stem}.png").is_file(),
                "fig_sha256": (sha256(figure_dir / f"{stem}.fig")
                               if (figure_dir / f"{stem}.fig").is_file() else None),
                "png_sha256": (sha256(figure_dir / f"{stem}.png")
                               if (figure_dir / f"{stem}.png").is_file() else None),
            }
    record["asset_manifest"] = asset_manifest(project)
    package = project / "仿真" / "仿真打包.zip"
    if package.is_file():
        record["simulation_package"] = inspect_package(package)
    for name in ("raw_results.csv", "raw_results.mat", "case_census.csv",
                 "simulation_cases.mat"):
        path = project / "仿真" / name
        if path.is_file():
            record.setdefault("raw_files", {})[name] = {
                "sha256": sha256(path), "bytes": path.stat().st_size,
            }
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--rule", type=Path, default=Path(__file__).with_name("README.md"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.project_dir.is_dir() or not args.rule.is_file():
        parser.error("project_dir and rule must exist")
    evidence = collect(args.project_dir, args.rule)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"Evidence: {args.output}")
    for language, item in evidence["docx"].items():
        print(f"{language} DOCX: OMML={item['omml_objects']} images={item['images']} "
              f"tables={item['tables']} CRC={item['zip_crc_bad_member']} "
              f"PAGE={item['footer_page_field']}")
    package = evidence.get("simulation_package")
    if package:
        print(f"Simulation package: members={package['members']} "
              f"CRC={package['zip_crc_bad_member']} "
              f"SHA256 match={package['sha256_matches_sidecar']}")


if __name__ == "__main__":
    main()
