---
name: gaki-waikan-organizer
description: Automatically categorizes and organizes downloaded English magazine study materials (外刊) into date-based folders with difficulty ratings and a sequential reading order.
license: Proprietary. LICENSE.txt has complete terms
---

# Waikan Organizer Skill

## Overview

This skill helps the user automatically sort, categorize, and rename a messy folder of downloaded English magazine materials (外刊) like The Economist or The Guardian. This includes mapping original articles (原文), intensive reading versions (精读), magazine layout versions (杂志排版), Q&A summaries (答疑汇总), and test questions (检验题) into structured grouped directories.

Use this skill when the user asks to "整理外刊", "organize my magazines", or points to a messy folder containing new downloads of their Kaoyan English materials.

## Behavior

When invoked, perform the following steps:

1. Locate the directory the user wants to organize (usually `Desktop/en/外刊` or whatever path they specify).
2. Ensure `pdfplumber` is installed (`pip install pdfplumber`).
3. If the user doesn't already have the `organize_waikan.py` script from previous sessions in the target directory, recreate the Python script from the section below.
4. Run the Python script on the target directory.
5. Provide a summary to the user following the Output Format below.

## Key Features

- **增量处理**: 已存在且大小相同的文件会被跳过，不会重复复制，可安全重复运行
- **日期零填充**: 日期格式从 `3.2` 统一为 `03.02`，确保文件夹按日期顺序排列
- **智能去重**: 当同一文件出现在多个源目录（如 `旧外刊/` 和 `新增下载/`）时，自动保留最新版本
- **缺失检测**: 自动检测每个日期缺少的材料类型并报告
- **统计报告**: 运行结束后输出详细统计（各类型文件数、新增/跳过数、缺失列表）

## Error Handling

- If `pdfplumber` fails to install (e.g. network restriction), notify the user and suggest `pip install pdfplumber --break-system-packages`
- If no date-pattern files are found after running the script, ask the user to confirm the directory path
- If the output folder (`整理后外刊文档`) already exists, the script runs in incremental mode by default — only new or changed files are copied. If the user explicitly requests a fresh start, warn them before wiping.
- If `pdfplumber` throws parsing errors, the fallback logic will safely skip to the next available PDF for that date without crashing the script.

## Output Format

After running the script, report:

- Total date folders created or modified
- New files copied vs skipped (already existing)
- File counts by category (原文, 精读, 杂志排版, 答疑汇总, 检验题)
- Any dates with missing materials and what's missing
- Any folders that are still `[难度未知]` (if any)
- The path to the output directory
- Any errors encountered during script execution

## Python Organization Script

If you need to generate or run the script, use the following code. It groups dates, extracts difficulty ratings from PDFs (falling back from "精读" to "杂志排版" to any other PDF), deduplicates across source folders, zero-pads dates for sorting, and renames files to match the user's preferred reading order.

```python
import os
import re
import shutil
import pdfplumber
from collections import defaultdict

# 需要跳过的文件扩展名
SKIP_EXTENSIONS = {'.py', '.bat', '.sh', '.js', '.json', '.log', '.tmp'}

# 文件类型分类和排序优先级
CATEGORY_MAP = [
    ('原文',   '1.原文'),
    ('精读',   '2.精读'),
    ('杂志排版', '3.杂志排版'),
    ('答疑',   '4.答疑汇总'),
    ('检验题',  '5.检验题'),
]
FALLBACK_CATEGORY = '6.其他'


def parse_date_key(date_str):
    """将 'M.DD' 格式的日期解析为 (month, day) 元组，用于排序。"""
    parts = date_str.split('.')
    try:
        return (int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return (99, 99)


def format_date_padded(date_str):
    """将 '3.2' 零填充为 '03.02'，使文件系统按字典序排列时即为日期顺序。"""
    month, day = parse_date_key(date_str)
    return f"{month:02d}.{day:02d}"


def get_difficulty(filepath):
    """从 PDF 首页提取难度评级（如 ★★★☆☆）。"""
    if not filepath.endswith('.pdf'):
        return None
    try:
        with pdfplumber.open(filepath) as pdf:
            if not pdf.pages:
                return None
            text = pdf.pages[0].extract_text()
            if not text:
                return None
            match = re.search(r'难度评级[：:]\s*(★+☆*)', text)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"  ⚠ 提取难度失败 {os.path.basename(filepath)}: {e}")
    return None


def is_weekly_original(filename):
    """判断文件是否是每周合并原文（日期范围格式）。"""
    return bool(re.search(r'\d+\.\d+[—\-~]\d+\.\d+\s*原文', filename))


def process_weekly_originals(src_dir, dest_dir):
    """将每周合并原文文档复制到专用子目录（增量模式）。"""
    weekly_folder = os.path.join(dest_dir, "每周合并原文合集")
    os.makedirs(weekly_folder, exist_ok=True)

    moved_count = 0
    skipped_count = 0
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if not is_weekly_original(file):
                continue
            src_path = os.path.join(root, file)
            if '每周合并原文合集' in src_path:
                continue
            dest_path = os.path.join(weekly_folder, file)
            if os.path.exists(dest_path) and os.path.getsize(dest_path) == os.path.getsize(src_path):
                skipped_count += 1
                continue
            shutil.copy2(src_path, dest_path)
            moved_count += 1

    return moved_count, skipped_count


def scan_daily_files(target_dir, output_dir):
    """
    扫描所有单独日期的学习材料。
    返回 { 'M.DD': [{'name': ..., 'path': ..., 'mtime': ...}, ...] }

    去重规则：同日期 + 同分类 + 同扩展名 → 保留修改时间最新的那个。
    不同扩展名（如 精读.pdf 和 精读.docx）会同时保留，因为用途不同。
    """
    output_abs = os.path.abspath(output_dir)
    # 去重 key = (date_str, category, ext)，不同扩展名视为不同文件
    seen = {}

    for root, dirs, files in os.walk(target_dir):
        abs_root = os.path.abspath(root)
        if abs_root.startswith(output_abs) or 'Test_Output' in abs_root:
            continue

        for file in files:
            if file.startswith('.'):
                continue
            _, ext = os.path.splitext(file)
            if ext.lower() in SKIP_EXTENSIONS:
                continue
            if is_weekly_original(file):
                continue

            date_match = re.search(r'(\d+\.\d+)', file)
            if not date_match:
                continue

            date_str = date_match.group(1)
            filepath = os.path.join(root, file)
            mtime = os.path.getmtime(filepath)

            category = _classify(file)
            dedup_key = (date_str, category, ext.lower())

            if dedup_key in seen:
                if mtime > seen[dedup_key]['mtime']:
                    seen[dedup_key] = {'name': file, 'path': filepath, 'mtime': mtime}
            else:
                seen[dedup_key] = {'name': file, 'path': filepath, 'mtime': mtime}

    daily_files = defaultdict(list)
    for (date_str, _, _), info in seen.items():
        daily_files[date_str].append(info)

    return dict(daily_files)


def _classify(filename):
    """返回文件的分类关键字。"""
    for keyword, _ in CATEGORY_MAP:
        if keyword in filename:
            return keyword
    return '其他'


def determine_new_name_and_order(filename):
    """根据文件名中的关键字决定重命名前缀和阅读排序。"""
    for keyword, prefix in CATEGORY_MAP:
        if keyword in filename:
            return f"{prefix} - {filename}"
    return f"{FALLBACK_CATEGORY} - {filename}"


def organize_files(base_dir, output_dir=None):
    if not output_dir:
        output_dir = os.path.join(base_dir, "整理后外刊文档")
    os.makedirs(output_dir, exist_ok=True)

    print("1. 正在提取并分离每周合并原文...")
    moved, skipped = process_weekly_originals(base_dir, output_dir)
    print(f"   ✅ 新增 {moved} 个, 跳过 {skipped} 个已存在的原文文档。")

    print("2. 正在扫描单独按日期的学习材料...")
    daily_files = scan_daily_files(base_dir, output_dir)
    sorted_dates = sorted(daily_files.keys(), key=parse_date_key)
    print(f"   📋 找到 {len(sorted_dates)} 个日期的资料。")

    print("3. 正在读取难度评级、分类与重命名...")
    stats = defaultdict(int)
    new_count = 0
    skip_count = 0
    unknown_dates = []

    for date in sorted_dates:
        files = daily_files[date]
        difficulty = "难度未知"

        pdf_priority = ['精读', '杂志排版']
        pdf_candidates = []
        for keyword in pdf_priority:
            for f in files:
                if keyword in f['name'] and f['name'].endswith('.pdf'):
                    pdf_candidates.append(f)
        for f in files:
            if f['name'].endswith('.pdf') and f not in pdf_candidates:
                pdf_candidates.append(f)

        for f in pdf_candidates:
            diff = get_difficulty(f['path'])
            if diff:
                difficulty = diff
                break

        if difficulty == "难度未知":
            unknown_dates.append(date)

        padded_date = format_date_padded(date)
        folder_name = f"[{difficulty}] {padded_date}"
        day_folder = os.path.join(output_dir, folder_name)
        os.makedirs(day_folder, exist_ok=True)

        for f in files:
            new_name = determine_new_name_and_order(f['name'])
            dest_path = os.path.join(day_folder, new_name)
            category = _classify(f['name'])
            stats[category] += 1

            if os.path.exists(dest_path) and os.path.getsize(dest_path) == os.path.getsize(f['path']):
                skip_count += 1
                continue

            shutil.copy2(f['path'], dest_path)
            new_count += 1

    # 统计报告
    print()
    print("=" * 50)
    print("📊 整理统计报告")
    print("=" * 50)
    print(f"   日期总数: {len(sorted_dates)}")
    print(f"   新复制文件: {new_count}")
    print(f"   跳过已有文件: {skip_count}")
    print()
    print("   各类型文件数量:")
    for keyword, prefix in CATEGORY_MAP:
        count = stats.get(keyword, 0)
        print(f"     {prefix}: {count} 个")
    other_count = stats.get('其他', 0)
    if other_count:
        print(f"     {FALLBACK_CATEGORY}: {other_count} 个")

    # 缺失检测
    print()
    expected_types = {'原文', '精读', '杂志排版', '答疑', '检验题'}
    gaps = []
    for date in sorted_dates:
        files = daily_files[date]
        found_types = set()
        for f in files:
            for keyword, _ in CATEGORY_MAP:
                if keyword in f['name']:
                    found_types.add(keyword)
                    break
        missing = expected_types - found_types
        if missing:
            gaps.append((date, missing))

    if gaps:
        print(f"⚠ 以下 {len(gaps)} 个日期存在缺失材料:")
        for date, missing in gaps:
            padded = format_date_padded(date)
            missing_str = ', '.join(sorted(missing))
            print(f"     {padded}: 缺少 [{missing_str}]")
    else:
        print("✅ 所有日期的材料均完整！")

    if unknown_dates:
        print()
        print(f"⚠ 以下 {len(unknown_dates)} 个日期无法识别难度评级:")
        for d in unknown_dates:
            print(f"     {format_date_padded(d)}")

    print()
    print(f"🎉 整理完成！所有归类文档保存在: {output_dir}")


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    organize_files(target)
```

## Additional Instructions

- **增量模式 (默认)**: 脚本默认以增量方式运行。已存在且大小相同的文件会被跳过，所以可以安全地在下载新文件后反复运行。
- **日期排序**: 日期文件夹使用零填充格式 (`01.18` 而非 `1.18`)，确保在文件管理器中按月日顺序排列。注意：首次优化后，旧的非零填充文件夹（如 `[★★★☆☆] 1.18`）不会被自动删除，可提示用户手动清理或帮用户删除旧格式文件夹。
- **去重逻辑**: 如果同一日期的同类型文件出现在多个源文件夹中（如 `旧外刊/` 和 `新增下载/`），脚本自动保留修改时间最新的版本。
- **难度未知处理**: 如果某个日期的文件夹仍显示 `[难度未知]`，说明该日期下所有 PDF（精读、杂志排版等）均未能提取到难度评级。应向用户说明缺少哪些文件，或建议检查下载来源（如"小鹅通网站里的经济学人考研英语"）。
- **迁移提示**: 如果用户之前已经有旧格式的输出（日期未零填充），建议用户删除 `整理后外刊文档` 目录后重新运行，以获得统一的零填充格式。
