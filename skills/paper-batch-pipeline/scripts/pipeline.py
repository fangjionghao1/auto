#!/usr/bin/env python3
"""Paper pipeline discovery, prompt composition, and evidence-aware ledger updates.

Standard library only. This tool verifies structure and hashes; humans/agents must
perform the scientific review and establish the authenticity of signatures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata

SCHEMA_VERSION = 1
PROGRESS = ("待处理", "执行中", "需重设计", "阻断", "待签署", "已完成")
GATES = ("design", "experiment", "independent_v2", "manuscript", "matlab_assets", "review")
ROLES = {
    "manuscript_md": {".md"}, "manuscript_docx": {".docx"},
    "raw_mat": {".mat"}, "raw_csv": {".csv"}, "matlab_entry": {".m"},
    "matlab_params": {".m", ".mat"}, "matlab_env": {".txt", ".md", ".json"},
    "matlab_run_log": {".txt", ".log", ".md"}, "figure_fig": {".fig"},
    "figure_png": {".png"}, "package": {".zip"},
}
RANK = {"已完成": 0, "待签署": 1, "待处理": 2, "执行中": 3, "需重设计": 4, "阻断": 5}
REPARSE_POINT = 0x400


class PipelineError(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def read_text(path):
    return Path(path).read_bytes().decode("utf-8-sig")


def normalized_text(text):
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).strip().split())


def norm_authors(value):
    if isinstance(value, list):
        pieces = [norm(v) for v in value]
    else:
        pieces = [norm(v) for v in re.split(r"[,，;；、]", str(value))]
    return tuple(v for v in pieces if v)


def inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def is_linklike(path):
    p = Path(path)
    try:
        st = p.lstat()
        return p.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & REPARSE_POINT)
    except OSError:
        return False


def assert_safe_path(path, root):
    p, root = Path(path).absolute(), Path(root).resolve()
    if not inside(p, root):
        raise PipelineError(f"Path is outside the allowed root: {p}")
    current = p
    while True:
        if is_linklike(current):
            raise PipelineError(f"Symlink/junction/reparse path is not allowed: {current}")
        if current == root:
            break
        if current.parent == current:
            raise PipelineError(f"Path does not descend from root: {p}")
        current = current.parent
    return p


def resolve_arg(value, workspace):
    p = Path(value)
    return p.absolute() if p.is_absolute() else (workspace / p).absolute()


def require_file(path, workspace):
    path = assert_safe_path(path, workspace)
    if not path.is_file():
        raise PipelineError(f"Required file does not exist: {path}")
    return path


def discover_goal(workspace, explicit=None):
    if explicit:
        return require_file(resolve_arg(explicit, workspace), workspace)
    candidates = [workspace / p for p in ("goal.md", "src/goal.md", "goal/进度表.md")]
    found = [p for p in candidates if p.is_file()]
    if len(found) != 1:
        raise PipelineError("Specify --goal: expected exactly one of goal.md, src/goal.md, goal/进度表.md; found " + str(len(found)))
    return require_file(found[0], workspace)


def discover_review(workspace, explicit=None):
    if explicit:
        return require_file(resolve_arg(explicit, workspace), workspace)
    candidates = [workspace / "test/README.md", workspace / "test/script/README.md"]
    found = [require_file(p, workspace) for p in candidates if p.is_file()]
    if not found:
        raise PipelineError("No review rule file found; specify --review.")
    if len(found) == 2 and normalized_text(read_text(found[0])) != normalized_text(read_text(found[1])):
        raise PipelineError("test/README.md and test/script/README.md differ. Specify --review explicitly; neither has been selected.")
    return found[0]


def signature_requirement(text):
    plain = re.sub(r"[*_`]+", "", text)
    names = re.findall(r"(?:并由|必须由|须由|需由|由)\s*([A-Za-z][\w.-]*|[\u4e00-\u9fff]{2,5})\s*签署", plain)
    names = list(dict.fromkeys(names))
    if len(names) > 1:
        return {"required": True, "signer": None, "source": "conflicting_named_signers", "candidates": names}
    if names:
        return {"required": True, "signer": names[0], "source": "named_rule_clause"}
    exemption = bool(re.search(r"(?:无需|不需要|免于)\s*(?:正式)?签署", plain))
    positive = bool(re.search(r"(?:必须|须|(?<!不)需要|应由|待)\s*.{0,16}签署", plain))
    return {"required": not (exemption and not positive), "signer": None,
            "source": "explicit_exemption" if exemption and not positive else "conservative_default_manual_review"}


def split_cells(line):
    # A pipe escaped with an odd number of backslashes belongs to a cell.
    separators = []
    for i, char in enumerate(line):
        if char != "|":
            continue
        count, j = 0, i - 1
        while j >= 0 and line[j] == "\\":
            count, j = count + 1, j - 1
        if count % 2 == 0:
            separators.append(i)
    if len(separators) < 2 or line[:separators[0]].strip() or line[separators[-1]+1:].strip():
        return None
    return [(line[a+1:b], a+1, b) for a, b in zip(separators, separators[1:])]


def clean_goal_path(value, workspace):
    value = value.strip().strip("`")
    match = re.fullmatch(r"\[[^\]]*\]\((?:<)?(.*?)(?:>)?\)", value)
    if match:
        value = match.group(1)
    if not value:
        return None
    # Existing ledgers commonly use Windows separators; accept them portably.
    value = value.replace("\\", os.sep).replace("/", os.sep)
    return resolve_arg(value, workspace).resolve()


def parse_goal(path, workspace):
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    aliases = {"id": {"稿件id", "项目id", "id"}, "title": {"标题", "文章题目", "题目", "title"},
               "authors": {"auth", "authors", "author", "作者", "署名"},
               "progress": {"进度", "progress"}, "path": {"产物路径", "项目路径", "路径", "path"}}
    rows, headers = [], []
    columns = None
    for index, line in enumerate(lines):
        cells = split_cells(line.rstrip("\r\n"))
        if not cells:
            columns = None
            continue
        values = [v[0].strip() for v in cells]
        lower = [norm(v).lower() for v in values]
        new_columns = {key: next((i for i, val in enumerate(lower) if val in names), None)
                       for key, names in aliases.items()}
        if all(new_columns[k] is not None for k in ("id", "title", "authors", "progress")):
            columns = new_columns
            headers.append(index)
            continue
        if columns is None or all(re.fullmatch(r":?-+:?", v.replace(" ", "")) for v in values):
            continue
        if len(values) <= max(c for c in columns.values() if c is not None):
            continue
        row = {key: values[col] if col is not None else "" for key, col in columns.items()}
        row.update({"line_index": index, "line_number": index + 1, "progress_index": columns["progress"],
                    "row_key": f"line:{index+1}", "resolved_path": clean_goal_path(row["path"], workspace)})
        rows.append(row)
    if not headers:
        raise PipelineError("Goal file has no Markdown table with ID, title, authors and progress columns.")
    return {"raw": raw, "text": text, "lines": lines, "rows": rows, "bom": raw.startswith(b"\xef\xbb\xbf")}


def prompt_identity(project, artifacts, rows):
    texts = [read_text(project / "src.md"), read_text(project / "speek.md")]
    titles, authors = [], []
    for text in texts:
        for match in re.finditer(r"^[ \t]*(?:文章题目|论文题目|标题|title)[ \t]*[:：][ \t]*(.*?)[ \t]*$", text, re.M | re.I):
            value = match.group(1).split("#", 1)[0].strip().strip("\"'")
            if value:
                titles.append(value)
        for match in re.finditer(r"^[ \t]*(?:作者|auth|authors)[ \t]*[:：][ \t]*(.*?)[ \t]*$", text, re.M | re.I):
            value = match.group(1).split("#", 1)[0].strip().strip("\"'")
            if value and not re.fullmatch(r"(?:待填|预留|待确认|未提供|无|TODO|TBD)(?:位)?", value, re.I):
                authors.append(value)
    title_values = set(norm(t) for t in titles)
    author_values = set(norm_authors(a) for a in authors)
    relparts = project.relative_to(artifacts).parts
    known_ids = {norm(r["id"]) for r in rows}
    found_ids = {part for part in relparts if norm(part) in known_ids}
    project_id = next(iter(found_ids)) if len(found_ids) == 1 else (relparts[0] if relparts else "")
    return {"project_id": project_id, "title": titles[-1] if titles else project.name,
            "authors": list(norm_authors(authors[-1])) if authors else [],
            "authors_source": "prompt" if authors else "unresolved",
            "title_source": "prompt" if titles else "directory_name",
            "conflicts": (["multiple_prompt_titles"] if len(title_values) > 1 else []) +
                         (["multiple_prompt_authors"] if len(author_values) > 1 else []) +
                         (["multiple_path_ids"] if len(found_ids) > 1 else [])}


def match_goal(project, identity, rows):
    id_candidates = [r for r in rows if norm(r["id"]) == norm(identity["project_id"])]
    base_candidates = [r for r in id_candidates if norm(r["title"]) == norm(identity["title"])]
    if identity["conflicts"]:
        return {"status": "conflict", "reason": ",".join(identity["conflicts"]),
                "candidates": [r["row_key"] for r in (base_candidates or id_candidates)]}
    candidates = base_candidates
    if identity["authors_source"] == "prompt":
        candidates = [r for r in candidates if norm_authors(r["authors"]) == tuple(identity["authors"])]
    exact_path = [r for r in candidates if r["resolved_path"] == project.resolve()]
    selected = exact_path if exact_path else candidates
    if len(selected) != 1:
        return {"status": "ambiguous" if len(selected) > 1 else "unmatched", "reason": "Exact ID/title/authors/path could not identify one goal row.",
                "candidates": [r["row_key"] for r in (selected or base_candidates or id_candidates)]}
    row = selected[0]
    if identity["authors_source"] != "prompt":
        identity["authors"] = list(norm_authors(row["authors"]))
        identity["authors_source"] = "goal"
    return {"status": "matched", "row_key": row["row_key"], "line_number": row["line_number"],
            "project_id": row["id"], "title": row["title"], "authors": list(norm_authors(row["authors"])),
            "path_match": bool(exact_path), "current_progress": row["progress"]}


def discover_projects(artifacts):
    if not artifacts.is_dir():
        raise PipelineError(f"Artifacts directory does not exist: {artifacts}")
    candidates, ignored = [], []
    for root, dirs, files in os.walk(artifacts, followlinks=False):
        root = Path(root)
        kept = []
        for name in sorted(dirs):
            p = root / name
            if is_linklike(p):
                ignored.append({"path": str(p), "reason": "symlink_or_junction"})
            elif name in {".paper-pipeline", ".git", "__pycache__"}:
                ignored.append({"path": str(p), "reason": "pipeline_or_runtime_metadata"})
            else:
                kept.append(name)
        dirs[:] = kept
        if "src.md" in files and "speek.md" in files:
            if is_linklike(root / "src.md") or is_linklike(root / "speek.md"):
                ignored.append({"path": str(root), "reason": "prompt_is_symlink_or_reparse"})
            else:
                candidates.append(root)
    leaves, shadowed = [], []
    for candidate in candidates:
        descendants = [p for p in candidates if p != candidate and candidate in p.parents]
        if descendants:
            shadowed.append({"path": str(candidate), "reason": "deeper_prompt_pair", "descendants": [str(p) for p in descendants]})
        else:
            leaves.append(candidate)
    return sorted(leaves, key=lambda p: str(p).casefold()), shadowed, ignored


def context(args):
    workspace = Path(args.workspace).absolute().resolve()
    if not workspace.is_dir():
        raise PipelineError(f"Workspace does not exist: {workspace}")
    artifacts = assert_safe_path(workspace / "gen/artifacts", workspace)
    goal = discover_goal(workspace, args.goal)
    review = discover_review(workspace, args.review)
    ledger = parse_goal(goal, workspace)
    return workspace, artifacts, goal, review, ledger


def collect(args):
    workspace, artifacts, goal, review, ledger = context(args)
    leaves, shadowed, ignored = discover_projects(artifacts)
    projects, excluded = [], []
    review_hash = sha256(review)
    for project in leaves:
        identity = prompt_identity(project, artifacts, ledger["rows"])
        match = match_goal(project, identity, ledger["rows"])
        item = {"path": str(project), "relative_path": project.relative_to(workspace).as_posix(),
                **identity, "goal_match": match, "inputs_sha256": {"src": sha256(project / "src.md"),
                "speek": sha256(project / "speek.md"), "review": review_hash},
                "status_path": str(project / ".paper-pipeline/status.json")}
        if getattr(args, "scope", "all") == "goal-paths" and not any(r["resolved_path"] == project.resolve() for r in ledger["rows"]):
            excluded.append({**item, "reason": "outside_explicit_goal_paths_scope"})
        else:
            projects.append(item)
    payload = {"workspace": str(workspace), "scope": getattr(args, "scope", "all"), "review_sha256": review_hash,
               "goal_sha256": sha256(goal), "projects": [(p["relative_path"], p["inputs_sha256"]) for p in projects]}
    batch_id = "batch-" + hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    for project in projects:
        project["batch_id"] = batch_id
    public = {"schema_version": SCHEMA_VERSION, "batch_id": batch_id,
              "workspace": str(workspace), "artifacts_root": str(artifacts), "goal": str(goal), "review": str(review),
              "goal_sha256": payload["goal_sha256"], "review_sha256": review_hash,
              "signature_requirement": signature_requirement(read_text(review)),
              "scope": payload["scope"], "project_count": len(projects), "projects": projects,
              "shadowed": shadowed, "excluded": excluded, "ignored": ignored,
              "notice": "Structural inventory only; no scientific conclusion or signature authenticity is established."}
    return public, ledger


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def emit_json(result, output=None, workspace=None):
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if output:
        path = resolve_arg(output, workspace)
        assert_safe_path(path, workspace)
        # An inventory snapshot must never overwrite source material or a ledger.
        if path.exists():
            raise PipelineError(f"Output exists; choose a new snapshot filename: {path}")
        atomic_write(path, content.encode("utf-8"))
    print(content, end="")


def command_scan(args):
    result, _ = collect(args)
    emit_json(result, args.output, Path(result["workspace"]))
    return 0


def command_compose(args):
    result, _ = collect(args)
    workspace, artifacts = Path(result["workspace"]), Path(result["artifacts_root"])
    project = assert_safe_path(resolve_arg(args.project, workspace), artifacts)
    selected = next((p for p in result["projects"] if Path(p["path"]).resolve() == project.resolve()), None)
    if selected is None:
        raise PipelineError("--project must be an eligible logical leaf with src.md and speek.md; a shadowed parent is not eligible.")
    template_path = Path(__file__).resolve().parent.parent / "references/master-prompt.md"
    if not template_path.is_file():
        raise PipelineError(f"Skill template missing: {template_path}")
    template = normalized_text(read_text(template_path))
    values = {"workspace": str(workspace), "artifacts_root": str(artifacts), "project": str(project), "review": result["review"], "goal": result["goal"],
              "src_sha256": selected["inputs_sha256"]["src"], "speek_sha256": selected["inputs_sha256"]["speek"],
              "review_sha256": result["review_sha256"], "batch_id": result["batch_id"]}
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    unresolved = re.findall(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}", template)
    if unresolved:
        raise PipelineError("Unrecognized template placeholders: " + ", ".join(unresolved))
    sections = [template.rstrip()]
    for label, source in (("PROJECT SOURCE: src.md", project / "src.md"),
                          ("PROJECT SUPPLEMENT: speek.md", project / "speek.md"),
                          ("REVIEW RULES", Path(result["review"]))):
        # The unique boundary is metadata, never an authority or execution boundary.
        boundary = "SOURCE-" + sha256(source)[:16]
        original = read_text(source)
        sections.append(f"## {label}\n\nSource: {source}\nSHA-256: {sha256(source)}\n\n<!-- BEGIN {boundary} -->\n{original}" +
                        ("" if original.endswith(("\n", "\r")) else "\n") + f"<!-- END {boundary} -->")
    content = "\n\n".join(sections) + "\n"
    destination = assert_safe_path(project / "final_prompt.md", workspace)
    encoded = content.encode("utf-8")
    if not destination.exists() or destination.read_bytes() != encoded:
        if destination.exists():
            history = assert_safe_path(project / ".paper-pipeline/history", workspace)
            history.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup = history / f"final_prompt.{stamp}.{sha256(destination)[:12]}.md"
            shutil.copy2(destination, backup)
        atomic_write(destination, encoded)
    sys.stdout.write(content)
    return 0


def evidence_file(entry, project, workspace, *, allow_workspace=False):
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"].strip():
        raise PipelineError("Evidence requires a nonempty path.")
    digest = entry.get("sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise PipelineError(f"Evidence has no valid SHA-256: {entry.get('path')}")
    p = Path(entry["path"])
    p = p if p.is_absolute() else project / p
    p = assert_safe_path(p, workspace if allow_workspace else project)
    if not p.is_file():
        raise PipelineError(f"Evidence file missing: {p}")
    if p.stat().st_size == 0:
        raise PipelineError(f"Evidence file is empty: {p}")
    if sha256(p) != digest.lower():
        raise PipelineError(f"Evidence hash mismatch: {p}")
    return p


def validate_status(item, snapshot):
    path, project, workspace = Path(item["status_path"]), Path(item["path"]), Path(snapshot["workspace"])
    if not path.is_file():
        return {"valid_identity": False, "progress": "待处理", "errors": ["status.json missing; goal row left unchanged"]}
    try:
        assert_safe_path(path, workspace)
        state = json.loads(read_text(path))
    except (ValueError, OSError, PipelineError) as exc:
        return {"valid_identity": False, "progress": "阻断", "errors": [str(exc)]}
    if not isinstance(state, dict):
        return {"valid_identity": False, "progress": "阻断", "errors": ["status.json must be an object"]}
    expected = item["goal_match"]
    identity_ok = (state.get("schema_version") == 1 and
                   norm(state.get("project_id", "")) == norm(expected.get("project_id", "")) and
                   norm(state.get("title", "")) == norm(expected.get("title", "")) and
                   norm_authors(state.get("authors", "")) == norm_authors(expected.get("authors", [])))
    if not identity_ok:
        return {"valid_identity": False, "progress": "阻断", "errors": ["status schema or exact ID/title/authors differs from the resolved goal row"]}
    progress = state.get("progress")
    if progress not in PROGRESS:
        return {"valid_identity": False, "progress": "阻断", "errors": ["Unknown progress value"]}
    errors = []
    if progress in {"待签署", "已完成"}:
        inputs = state.get("inputs_sha256", {})
        if inputs != item["inputs_sha256"]:
            errors.append("Input hashes are missing, stale, or differ from current src/speek/review.")
        prompt = project / "final_prompt.md"
        try:
            assert_safe_path(prompt, workspace)
            if not prompt.is_file() or state.get("prompt_sha256") != sha256(prompt):
                errors.append("final_prompt.md is missing or its hash does not match status.")
        except (OSError, PipelineError) as exc:
            errors.append(str(exc))
        gates = state.get("gates", {})
        for gate in GATES:
            value = gates.get(gate) if isinstance(gates, dict) else None
            if isinstance(value, dict):
                value = value.get("status")
            if value != "pass":
                errors.append(f"Gate is not pass: {gate}")
        roles = set()
        figure_paths = {"figure_fig": set(), "figure_png": set()}
        artifacts = state.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
            errors.append("artifacts must be a list.")
        for artifact in artifacts:
            try:
                p = evidence_file(artifact, project, workspace)
                role = artifact.get("role")
                if role in ROLES:
                    if p.suffix.lower() not in ROLES[role]:
                        raise PipelineError(f"Wrong extension for artifact role {role}: {p}")
                    roles.add(role)
                    if role in figure_paths:
                        figure_paths[role].add(os.path.normcase(str(p.with_suffix("").resolve())))
            except (PipelineError, OSError) as exc:
                errors.append(str(exc))
        for missing in sorted(set(ROLES) - roles):
            errors.append(f"Required artifact role missing or invalid: {missing}")
        for unmatched in sorted(figure_paths["figure_fig"] ^ figure_paths["figure_png"]):
            errors.append(f"MATLAB FIG/PNG must be declared in same-directory, same-stem pairs: {unmatched}")
        review = state.get("review", {})
        try:
            evidence_file(review, project, workspace, allow_workspace=True)
        except (PipelineError, OSError) as exc:
            errors.append("Review report: " + str(exc))
        if not isinstance(review, dict):
            review = {}
        if review.get("rule_sha256") != snapshot["review_sha256"]:
            errors.append("Review report is not bound to the current rules hash.")
        if review.get("prompt_sha256") != state.get("prompt_sha256") or not state.get("prompt_sha256"):
            errors.append("Review report is not bound to the current final prompt hash.")
        if type(review.get("blocker_count")) is not int or review.get("blocker_count") != 0:
            errors.append("Review has unresolved or unspecified Blocker count.")
        if type(review.get("major_count")) is not int or review.get("major_count") != 0:
            errors.append("Review has unresolved or unspecified Major count.")
        signature = state.get("signature", {})
        if not isinstance(signature, dict):
            signature = {}
        required = snapshot["signature_requirement"]["required"]
        if type(signature.get("required")) is not bool:
            errors.append("signature.required must be a boolean.")
        elif required and signature["required"] is not True:
            errors.append("Rule signature requirement cannot be disabled by status.json.")
        required = required or signature.get("required", True)
        if progress == "已完成" and required:
            signer = signature.get("signer", "")
            if not isinstance(signer, str) or not signer.strip():
                errors.append("Required signer is missing.")
            named = snapshot["signature_requirement"].get("signer")
            if named and norm(signer) != norm(named):
                errors.append(f"Signer differs from the review rule ({named}).")
            if snapshot["signature_requirement"].get("source") == "conflicting_named_signers":
                errors.append("Review rules name conflicting signers; resolve manually before completion.")
            try:
                evidence_file({"path": signature.get("evidence_path"), "sha256": signature.get("evidence_sha256")},
                              project, workspace, allow_workspace=True)
            except (PipelineError, OSError) as exc:
                errors.append("Signature evidence: " + str(exc))
    return {"valid_identity": True, "requested_progress": progress, "progress": "阻断" if errors else progress,
            "errors": errors, "reason": state.get("reason", ""), "phase": state.get("phase", "")}


def command_update_goal(args):
    snapshot, ledger = collect(args)
    groups, unresolved = {}, []
    for item in snapshot["projects"]:
        match = item["goal_match"]
        if match["status"] != "matched":
            unresolved.append({"path": item["path"], "goal_match": match})
            continue
        check = validate_status(item, snapshot)
        groups.setdefault(match["row_key"], []).append({"path": item["path"], **check})
    affected_ambiguous = {key for item in unresolved for key in item["goal_match"].get("candidates", [])}
    lines, changes, skipped = list(ledger["lines"]), [], []
    for row in ledger["rows"]:
        members = groups.get(row["row_key"], [])
        if not members:
            continue
        if row["row_key"] in affected_ambiguous or any(not m["valid_identity"] for m in members):
            skipped.append({"row_key": row["row_key"], "project_id": row["id"], "reason": "Unresolved, missing, or conflicting project identity/status; entire aggregate row unchanged.", "projects": members})
            continue
        aggregate = max((m["progress"] for m in members), key=lambda p: RANK[p])
        change = {"row_key": row["row_key"], "project_id": row["id"], "title": row["title"],
                  "authors": list(norm_authors(row["authors"])), "from": row["progress"], "to": aggregate,
                  "changed": row["progress"] != aggregate, "projects": members}
        changes.append(change)
        if not change["changed"]:
            continue
        line = lines[row["line_index"]]
        cell, start, end = split_cells(line.rstrip("\r\n"))[row["progress_index"]]
        prefix = cell[:len(cell) - len(cell.lstrip())]
        suffix = cell[len(cell.rstrip()):]
        # Preserve original padding, all other cells, line endings, and BOM.
        lines[row["line_index"]] = line[:start] + prefix + aggregate + suffix + line[end:]
    newbytes = (b"\xef\xbb\xbf" if ledger["bom"] else b"") + "".join(lines).encode("utf-8")
    result = {"schema_version": 1, "batch_id": snapshot["batch_id"], "mode": "apply" if args.apply else "dry-run",
              "scope": snapshot["scope"], "goal": snapshot["goal"], "review": snapshot["review"],
              "signature_requirement": snapshot["signature_requirement"], "changes": changes, "skipped": skipped,
              "unresolved": unresolved, "excluded": snapshot["excluded"], "shadowed": snapshot["shadowed"],
              "written": False, "notice": "Only structural/hash checks are automated. Scientific gate judgments and signature authenticity remain reviewer responsibilities."}
    if args.apply and newbytes != ledger["raw"]:
        goal = Path(snapshot["goal"])
        if goal.read_bytes() != ledger["raw"]:
            raise PipelineError("Goal changed during validation; no update written. Retry from a fresh scan.")
        history = assert_safe_path(goal.parent / ".paper-pipeline/history", Path(snapshot["workspace"]))
        history.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = history / f"{goal.name}.{stamp}.{snapshot['goal_sha256'][:12]}.bak"
        shutil.copy2(goal, backup)
        atomic_write(goal, newbytes)
        result.update({"written": True, "backup": str(backup), "new_goal_sha256": sha256(goal)})
    emit_json(result)
    return 0


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    for name, help_text in (("scan", "Inventory logical project leaves; read only."),
                            ("compose", "Save and echo the complete prompt, preserving prior versions."),
                            ("update-goal", "Aggregate verified project states; dry-run unless --apply.")):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--workspace", required=True, help="Workspace root containing gen/artifacts.")
        sub.add_argument("--goal", help="Explicit workspace-relative or absolute goal file; otherwise uniquely discover standard locations.")
        sub.add_argument("--review", help="Explicit rule file, required when both standard README files differ.")
        if name != "compose":
            sub.add_argument("--scope", choices=("all", "goal-paths"), default="all", help="Default: every eligible version; goal-paths is an explicit current-path filter.")
        if name == "scan":
            sub.add_argument("--output", help="Optional new JSON snapshot path inside workspace; existing files are never overwritten.")
        elif name == "compose":
            sub.add_argument("--project", required=True, help="Eligible project path inside gen/artifacts.")
        else:
            sub.add_argument("--apply", action="store_true", help="Apply only progress-cell changes, with backup and atomic replacement.")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return {"scan": command_scan, "compose": command_compose, "update-goal": command_update_goal}[args.command](args)
    except (PipelineError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="")
        sys.stderr.reconfigure(encoding="utf-8", newline="")
    raise SystemExit(main())
