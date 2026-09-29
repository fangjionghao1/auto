"""Generate manuscript source files from unfinished rows in src/goal.md.

Skips rows whose 进度 is 完成/已完成/进行中. After generating, marks those
rows as 进行中 in goal.md.

Run from any directory: python generate_src.py
"""

from pathlib import Path
import json
import re
import shutil


ROOT = Path(__file__).resolve().parent
GOAL = ROOT / "src" / "goal.md"
TEMPLATE = ROOT / "gen-src-repo" / "src.md"
SPEEK = ROOT / "gen-src-repo" / "speek.md"
OUTPUT = ROOT / "gen" / "artifacts"


def table_rows(text):
    rows = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if cells:
            rows.append(cells)
    if len(rows) < 2:
        raise ValueError("goal.md 中未找到表格")
    headers = rows[0]
    required = ("稿件ID", "状态", "标题", "type", "进度")
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"goal.md 缺少列：{', '.join(missing)}")
    for cells in rows[1:]:
        if len(cells) != len(headers) or all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        yield dict(zip(headers, cells))


def directory_part(value, field):
    value = value.strip()
    if not value or value in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError(f"无效的{field}目录名：{value!r}")
    if value.endswith((" ", ".")):
        raise ValueError(f"无效的{field}目录名：{value!r}")
    return value


def yaml_scalar(value):
    # Plain scalars are easier to read; quote values that would change YAML syntax.
    if not value or re.search(r"[:#\[\]{},&*!|>'\"%@`]|^[-?]\s|\s$", value):
        return json.dumps(value, ensure_ascii=False)
    return value


def replace_parameters(template, title, journal, language):
    section = re.search(r"(?m)^## §0 参数区（使用前替换）\s*$", template)
    if not section:
        raise ValueError("src.md 中未找到 §0 参数区")
    fence = re.search(r"(?m)^```yaml[ \t]*\r?$", template[section.end():])
    if not fence:
        raise ValueError("§0 中未找到 YAML 代码块")
    start = section.end() + fence.end()
    close = re.search(r"(?m)^```[ \t]*\r?$", template[start:])
    if not close:
        raise ValueError("§0 的 YAML 代码块未闭合")
    end = start + close.start()
    block = template[start:end]
    values = {"文章题目": title, "预投期刊": journal, "目标语言": language}
    for key, value in values.items():
        pattern = re.compile(rf"(?m)^([ \t]*{key}:[ \t]*)([^\r\n#]*?)([ \t]*(?:#[^\r\n]*)?)(\r?$)")
        matches = list(pattern.finditer(block))
        if len(matches) != 1:
            raise ValueError(f"§0 的 YAML 中应恰有一个 {key} 参数")
        block = pattern.sub(lambda m: m.group(1) + yaml_scalar(value) + m.group(3) + m.group(4), block, count=1)
    return template[:start] + block + template[end:]


def mark_progress(ids, progress="进行中"):
    """Set 进度 to `progress` for rows whose 稿件ID is in ids. Preserves cell padding."""
    lines = GOAL.read_text(encoding="utf-8-sig").splitlines()
    header = None
    for line in lines:
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if "稿件ID" in cells and "进度" in cells:
                header = cells
                break
    if header is None:
        raise ValueError("goal.md 中未找到包含 稿件ID/进度 的表头")
    id_col, prog_col = header.index("稿件ID"), header.index("进度")
    marked = 0
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        parts = re.split(r"(?<!\\)\|", line)
        cells = [cell.strip() for cell in parts[1:-1]]
        if len(cells) != len(header):
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if cells[id_col] in ids and cells[prog_col] != progress:
            parts[prog_col + 1] = f" {progress} "
            lines[index] = "|".join(parts)
            marked += 1
    if marked:
        GOAL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return marked


def main():
    rows = list(table_rows(GOAL.read_text(encoding="utf-8-sig")))
    template = TEMPLATE.read_bytes().decode("utf-8")
    if not SPEEK.is_file():
        raise FileNotFoundError(SPEEK)
    count = 0
    generated_ids = []
    for row in rows:
        if row["进度"].strip() in ("完成", "已完成", "进行中"):
            continue
        manuscript_id = directory_part(row["稿件ID"], "稿件ID")
        status = directory_part(row["状态"], "状态")
        title = directory_part(row["标题"], "标题")
        journal = row["type"].strip()
        language = "中英双稿" if journal.startswith("EI会议") else "中文稿"
        content = replace_parameters(template, title, journal, language)
        destination = OUTPUT / manuscript_id / status / title
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "src.md").write_bytes(content.encode("utf-8"))
        shutil.copyfile(SPEEK, destination / "speek.md")
        print(destination)
        generated_ids.append(manuscript_id)
        count += 1
    print(f"生成 {count} 篇稿件")
    if generated_ids:
        marked = mark_progress(generated_ids)
        print(f"goal.md 标记进行中 {marked} 行")


if __name__ == "__main__":
    main()
