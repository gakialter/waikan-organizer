import os
import re
import sys
import shutil
import pdfplumber
from collections import defaultdict

# 修复 Windows 控制台中文 + emoji 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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
    """将每周合并原文文档复制到专用子目录。"""
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
            # 增量：如果目标文件已存在且大小相同，跳过
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
            # 跳过隐藏文件和脚本
            if file.startswith('.'):
                continue
            _, ext = os.path.splitext(file)
            if ext.lower() in SKIP_EXTENSIONS:
                continue

            # 跳过每周合并原文
            if is_weekly_original(file):
                continue

            # 匹配日期
            date_match = re.search(r'(\d+\.\d+)', file)
            if not date_match:
                continue

            date_str = date_match.group(1)
            filepath = os.path.join(root, file)
            mtime = os.path.getmtime(filepath)

            # 去重逻辑：同日期 + 同分类 + 同扩展名 → 保留更新的
            category = _classify(file)
            dedup_key = (date_str, category, ext.lower())

            if dedup_key in seen:
                if mtime > seen[dedup_key]['mtime']:
                    seen[dedup_key] = {'name': file, 'path': filepath, 'mtime': mtime}
            else:
                seen[dedup_key] = {'name': file, 'path': filepath, 'mtime': mtime}

    # 按日期聚合
    daily_files = defaultdict(list)
    for (date_str, _, _), info in seen.items():
        daily_files[date_str].append(info)

    return dict(daily_files)


def _classify(filename):
    """返回文件的分类关键字，用于去重和排序。"""
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

    # ── 第一步：每周合并原文 ──
    print("1. 正在提取并分离每周合并原文...")
    moved, skipped = process_weekly_originals(base_dir, output_dir)
    print(f"   ✅ 新增 {moved} 个, 跳过 {skipped} 个已存在的原文文档。")

    # ── 第二步：扫描单日材料 ──
    print("2. 正在扫描单独按日期的学习材料...")
    daily_files = scan_daily_files(base_dir, output_dir)
    # 按日期排序
    sorted_dates = sorted(daily_files.keys(), key=parse_date_key)
    print(f"   📋 找到 {len(sorted_dates)} 个日期的资料。")

    # ── 第三步：分类、提取难度、复制 ──
    print("3. 正在读取难度评级、分类与重命名...")
    stats = defaultdict(int)  # 统计每个分类的文件数
    new_count = 0
    skip_count = 0
    unknown_dates = []

    for date in sorted_dates:
        files = daily_files[date]
        difficulty = "难度未知"

        # 按优先级从 PDF 中提取难度：精读 > 杂志排版 > 其他PDF
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

        # 使用零填充日期创建文件夹
        padded_date = format_date_padded(date)
        folder_name = f"[{difficulty}] {padded_date}"
        day_folder = os.path.join(output_dir, folder_name)
        os.makedirs(day_folder, exist_ok=True)

        for f in files:
            new_name = determine_new_name_and_order(f['name'])
            dest_path = os.path.join(day_folder, new_name)
            category = _classify(f['name'])
            stats[category] += 1

            # 增量：如果目标已存在且大小相同，跳过
            if os.path.exists(dest_path) and os.path.getsize(dest_path) == os.path.getsize(f['path']):
                skip_count += 1
                continue

            shutil.copy2(f['path'], dest_path)
            new_count += 1

    # ── 第四步：统计报告 ──
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

    # ── 第五步：缺失材料检测 ──
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
    target = sys.argv[1] if len(sys.argv) > 1 else r'c:\Users\27296\Desktop\en\外刊'
    print("开始整理外刊文档：")
    organize_files(target)
