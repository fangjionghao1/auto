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
        match = re.match(r"^\s*([^：:]+)[：:]\s*(.*?)\s*$", line)
        if match:
            key, value = match.groups()
            key = key.strip()
            if key in (*FIELDS, "目标等级", "状态", "备注", "note"):
                current = key
                values[key] = value
            else:
                current = None
        elif current == "题目" and line[:1].isspace() and line.strip():
            values["题目"] += "\n" + line.strip()
        elif line.strip():
            current = None
    if any(not values.get(key, "").strip() for key in FIELDS):
        return None
    titles = [part.strip() for part in values["题目"].splitlines() if part.strip()]
    return values, titles


def safe_cell(value):
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "；")


def add_goal_rows(path, parsed, upload_date):
    values, titles = parsed
    existing = GOAL.read_text(encoding="utf-8-sig")
    rows = []
    for index, title in enumerate(titles, 1):
        manuscript_id = path.stem + "-" + upload_date.strftime("%m%d")
        if len(titles) > 1:
            manuscript_id += f"-{index}"
        if re.search(r"^\|\s*" + re.escape(manuscript_id) + r"\s*\|", existing, re.M):
            continue
        cells = [manuscript_id, values["作者"], title,
                 values.get("目标等级") or "正常", values.get("状态") or "V1",
                 str(path.resolve()), "", values.get("备注") or values.get("note") or "", ""]
        rows.append("| " + " | ".join(safe_cell(cell) for cell in cells) + " |")
    if rows:
        lines = existing.splitlines()
        lines = [line for line in lines if not re.fullmatch(r"\|(?:\s*\|){9}", line)]
        GOAL.write_text("\n".join(lines).rstrip() + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def poll(repo, branch, state):
    items = gh("api", f"repos/{repo}/contents/src?ref={quote(branch)}")
    if not isinstance(items, list):
        raise RuntimeError("GitHub src is not a directory")
    names = {item["name"]: item for item in items if item.get("type") == "file"
             and item["name"].lower().endswith(".txt") and item["name"] != "1.txt"
             and not item["name"].lower().endswith(".faild.txt")}
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
                "格式校验失败：缺少部门、采编、订单时间、类别、作者或题目。\n", encoding="utf-8")
            print(f"Ignored invalid file: {name}", flush=True)
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
