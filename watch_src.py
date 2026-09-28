"""Poll GitHub's src directory and add new manuscripts to src/goal.md.

Requires GitHub CLI (gh) installed and authenticated. Run from any directory:
    python watch_src.py
    python watch_src.py --once
"""

import argparse
import base64
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
GOAL = SRC / "goal.md"
STATE = ROOT / ".git" / "watch-src-state.json"
FIELDS = ("部门", "采编", "订单时间", "类别", "作者", "题目")


def gh(*args):
    result = subprocess.run(["gh", *args], cwd=ROOT, text=True,
                            encoding="utf-8", capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"gh exited with {result.returncode}")
    return json.loads(result.stdout)


def parse_manuscripts(content):
    values = {}
    current = None
    for line in content.splitlines():
        matches = list(re.finditer(
            r"(?<!\S)(部门|采编|订单时间|类别|作者|题目|目标等级|状态|备注|note)[：:]",
            line,
        ))
        if matches:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
                current = match.group(1)
                values[current] = line[match.end():end].strip()
        elif current == "题目" and line[:1].isspace() and line.strip():
            values["题目"] += "\n" + line.strip()
        elif line.strip():
            current = None
    if any(not values.get(key, "").strip() for key in FIELDS if key != "作者"):
        return None
    values.setdefault("作者", "")
    titles = [part.strip() for part in values["题目"].splitlines() if part.strip()]
    return values, titles


def safe_cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "；")


def goal_table():
    lines = GOAL.read_text(encoding="utf-8-sig").splitlines()
    rows = []
    for line in lines:
        if line.startswith("|"):
            rows.append([cell.strip().replace("\\|", "|")
                         for cell in re.split(r"(?<!\\)\|", line)[1:-1]])
    if not rows:
        raise ValueError("goal.md has no table header")
    return lines, rows[0], rows[2:]


def historical_manuscripts():
    """Read author/title pairs whose recorded source is a file in src."""
    found = set()
    _, headers, rows = goal_table()
    source_index = headers.index("src") if "src" in headers else headers.index("产物路径")
    for cells in rows:
        if len(cells) <= source_index or not cells[0]:
            continue
        source = Path(cells[source_index].replace("\\", "/"))
        if source.parent.name.lower() == "src" and source.suffix.lower() == ".txt":
            found.add((" ".join(cells[headers.index("auth")].split()),
                       " ".join(cells[headers.index("标题")].split())))
    return found


def manuscript_pairs(parsed):
    values, titles = parsed
    author = " ".join(values["作者"].split())
    return {(author, " ".join(title.split())) for title in titles}


def duplicate_title(parsed, reference_pairs=()):
    values, titles = parsed
    existing = historical_manuscripts() | set(reference_pairs)
    author = " ".join(values["作者"].split())
    return next((title for title in titles if (author, " ".join(title.split())) in existing), None)


def duplicate_destination(path):
    target = path.with_name(path.stem + ".duplicate.txt")
    number = 2
    while target.exists():
        target = path.with_name(f"{path.stem}-{number}.duplicate.txt")
        number += 1
    return target


def add_goal_rows(path, parsed, upload_date):
    values, titles = parsed
    lines, headers, old_rows = goal_table()
    existing_ids = {row[headers.index("稿件ID")] for row in old_rows
                    if len(row) == len(headers)}
    rows = []
    for index, title in enumerate(titles, 1):
        manuscript_id = path.stem + "-" + upload_date.strftime("%m%d")
        if len(titles) > 1:
            manuscript_id += f"-{index}"
        if manuscript_id in existing_ids:
            continue
        record = {"稿件ID": manuscript_id, "auth": values["作者"],
                  "type": values["类别"], "标题": title,
                  "目标等级": values.get("目标等级") or "正常",
                  "状态": values.get("状态") or "V1",
                  "note": values.get("备注") or values.get("note") or "",
                  "src": str(path.resolve())}
        if "src" not in headers:
            record["产物路径"] = str(path.resolve())
        rows.append("| " + " | ".join(safe_cell(record.get(header, "")) for header in headers) + " |")
    if rows:
        lines = [line for line in lines if not re.fullmatch(r"\|(?:\s*\|){" + str(len(headers)) + r"}", line)]
        GOAL.write_text("\n".join(lines).rstrip() + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def poll(repo, branch, state):
    items = gh("api", f"repos/{repo}/contents/src?ref={quote(branch)}")
    if not isinstance(items, list):
        raise RuntimeError("GitHub src is not a directory")
    reference_pairs = set()
    if any(item.get("name") == "1.txt" for item in items):
        reference_data = gh("api", f"repos/{repo}/contents/src/1.txt?ref={quote(branch)}")
        reference_text = base64.b64decode(reference_data["content"]).decode("utf-8-sig")
        reference = parse_manuscripts(reference_text)
        if reference:
            reference_pairs = manuscript_pairs(reference)
    names = {item["name"]: item for item in items if item.get("type") == "file"
             and item["name"].lower().endswith(".txt") and item["name"] != "1.txt"
             and not item["name"].lower().endswith((".faild.txt", ".duplicate.txt"))}
    for name, item in sorted(names.items()):
        if name in state:
            continue
        path = SRC / name
        data = gh("api", f"repos/{repo}/contents/{quote('src/' + name, safe='/')}?ref={quote(branch)}")
        content = base64.b64decode(data["content"]).decode("utf-8-sig")
        path.write_text(content, encoding="utf-8")
        parsed = parse_manuscripts(content)
        if parsed is None:
            path.with_name(path.stem + ".faild.txt").write_text(
                "格式校验失败：缺少部门、采编、订单时间、类别或题目。\n", encoding="utf-8")
            print(f"Ignored invalid file: {name}", flush=True)
        elif duplicate_title(parsed, reference_pairs):
            target = duplicate_destination(path)
            path.rename(target)
            print(f"Duplicate {name}: renamed to {target.name}", flush=True)
        else:
            commits = gh("api", f"repos/{repo}/commits?path={quote('src/' + name, safe='/')}&per_page=1")
            stamp = commits[0]["commit"]["committer"]["date"]
            upload_date = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date()
            count = add_goal_rows(path, parsed, upload_date)
            print(f"Processed {name}: {count} goal row(s)", flush=True)
        state[name] = item["sha"]
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one poll then exit")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval must be positive")
    if not GOAL.exists() or not (ROOT / ".git").exists():
        parser.error("Run in the repository containing src/goal.md")
    try:
        repo_info = gh("repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    except FileNotFoundError:
        parser.error("GitHub CLI (gh) is required; install it and run gh auth login")
    repo = repo_info["nameWithOwner"]
    branch = repo_info["defaultBranchRef"]["name"]
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    while True:
        try:
            poll(repo, branch, state)
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            print(f"Poll failed: {exc}", file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
