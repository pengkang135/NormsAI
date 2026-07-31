"""
提取结果自动校验：在 extract_auto.py 输出与入库之间运行。

校验规则（按严重程度分级）：

  FATAL — 入库阻断，必须修复
  ERROR — 数据受损，需复核
  WARN  — 可疑，建议人工确认

用法:
  python scripts/validate_extraction.py                    # 校验全部
  python scripts/validate_extraction.py 155                # 校验单页
  python scripts/validate_extraction.py 140-180            # 校验范围
  python scripts/validate_extraction.py --db               # 校验已入库的DB数据
"""

import json, sys, os, re, io
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
EXTRACTED_DIR = ROOT / "output" / "intermediate" / "extracted"

UNIT_WORDS = {
    '工日', '台班', '元', 'm3', 'm²', 'm³', 'm', 't', 'kg', '10m3', '100m3', '100m2',
    '艘班', '组', '根', '榀', '%', '件', '个', '块', '套', '只', '条', '片', '座', '处', '段',
    '延长米', 'km', 'm²', '㎡', '10m³', '10m', '100m²',
}


def slug(s):
    return re.sub(r'\s+', ' ', s).strip()


# ─── 校验函数 ───

def check_cost_items(data, page):
    """校验费用项目。

    FATAL: cost_item 是纯单位词（如 m³, 工日）
    ERROR: cost_item 为空或缺失
    WARN:  费用项目名含异常字符
    """
    issues = []
    cost_items = data.get('cost_items', [])
    items = data.get('items', [])

    if not cost_items and items:
        # 从items反推
        seen = set()
        for item in items:
            ci = item.get('cost_item', '')
            if ci and ci not in seen:
                seen.add(ci)
                cost_items = [{'name': ci, 'unit': item.get('cost_item_unit', '')}]
        if not cost_items:
            issues.append(('FATAL', f'cost_items 为空但 items 有 {len(items)} 条'))

    for ci in cost_items:
        name = ci.get('name', '') if isinstance(ci, dict) else str(ci)
        if not name:
            issues.append(('ERROR', f'cost_item 名称为空'))
        elif name in UNIT_WORDS:
            # 尝试找原始文本确认是否真的是费用项目
            issues.append(('FATAL', f'费用项目为纯单位词: "{name}" (unit={ci.get("unit","")}, code={ci.get("code","")})'))

    # 检查items中每次出现的cost_item
    item_names = set()
    for item in items:
        ci = item.get('cost_item', '')
        if ci in UNIT_WORDS:
            item_names.add(ci)
    for name in sorted(item_names):
        cnt = sum(1 for item in items if item.get('cost_item') == name)
        issues.append(('FATAL', f'items 中有 {cnt} 条 cost_item="{name}"（纯单位词）'))

    return issues


def check_attr_dimensions(data, page):
    """校验属性维度。

    FATAL: norms_codes 有值但 attr_dimensions 中 values 长度不匹配
    WARN:  attr_dimensions 为空（可能真的是单维表，也可能漏提取）
    """
    issues = []
    codes = data.get('norms_codes') or []
    n_codes = len(codes)

    dims = data.get('attr_dimensions', [])
    if not dims:
        if n_codes > 1:
            # 多列但无属性维度 → 可能是漏提取
            # 但也可能是纯多列定额编号无属性区分
            # 检查表头是否真的有属性文本
            issues.append(('WARN', f'{n_codes} 个定额编号但 attr_dimensions 为空'))
        return issues

    for dim in dims:
        name = dim.get('name', '')
        vals = dim.get('values', [])
        if not name:
            issues.append(('ERROR', f'attr_dimension 名称为空'))
        if len(vals) != n_codes:
            issues.append(('FATAL',
                f'attr "{name}" 的 values 长度 ({len(vals)}) != codes 数量 ({n_codes})'))
        # 检查是否所有值都相同（可能是常量属性提取失败）
        non_empty = [v for v in vals if v]
        if len(set(non_empty)) == 1 and len(vals) > 1:
            issues.append(('WARN',
                f'attr "{name}" 所有值相同: "{non_empty[0]}" — 可能是跨列属性未正确拆分'))

    return issues


def check_work_content(data, page):
    """校验工程内容。

    ERROR: 括号编号不连续 (有(1)和(3)但缺(2))
    WARN:  以分号结尾可能截断
    """
    issues = []
    wc = data.get('work_content', '')
    if not wc:
        return issues

    # 提取所有括号编号
    nums = [int(m.group(1)) for m in re.finditer(r'[（(](\d+)[）)]', wc)]
    if nums:
        expected = list(range(1, max(nums) + 1))
        missing = set(expected) - set(nums)
        if missing:
            issues.append(('ERROR',
                f'工程内容编号不连续: 缺 {sorted(missing)} (现有 {sorted(nums)})'))

    if wc.rstrip().endswith('；') or wc.rstrip().endswith(';'):
        issues.append(('WARN', '工程内容以分号结尾，可能截断（应包含所有编号项）'))

    return issues


def check_norms_codes(data, page):
    """校验定额编号。

    FATAL: codes 为 None 或空（非续表页）
    ERROR: codes 数量与 items 中唯一 codes 数不一致
    WARN:  codes 不都是5位数字
    """
    issues = []
    codes = data.get('norms_codes') or []
    items = data.get('items', [])

    if not codes:
        if items:
            issues.append(('FATAL', 'norms_codes 为空但有 items 数据'))
        return issues

    for code in codes:
        if not re.match(r'^\d{5}$', str(code)):
            issues.append(('WARN', f'定额编号 "{code}" 不是5位数字'))

    # 检查items中实际使用的codes
    item_codes = set()
    for item in items:
        qc = item.get('norms_code') or item.get('quota_code') or ''
        if qc:
            item_codes.add(qc)
    missing_in_items = set(codes) - item_codes
    extra_in_items = item_codes - set(codes)
    if missing_in_items:
        issues.append(('ERROR', f'声明了但未使用的 codes: {missing_in_items}'))
    if extra_in_items:
        issues.append(('WARN', f'items 中有未声明的 codes: {extra_in_items}'))

    return issues


def check_item_counts(data, page):
    """校验条目数量一致性。

    ERROR: 实际条目数 != len(cost_items) × len(norms_codes)
    WARN:  amount 全为 None 的费用项目
    """
    issues = []
    codes = data.get('norms_codes') or []
    cost_items = data.get('cost_items', [])
    items = data.get('items', [])

    if codes and cost_items:
        expected = len(cost_items) * len(codes)
        actual = len(items)
        if actual != expected:
            issues.append(('ERROR',
                f'条目数不匹配: 实际 {actual} != 期望 {expected} ({len(cost_items)}费用×{len(codes)}编号)'))

    # 检查是否有费用项目所有amount都为None
    by_cost = defaultdict(list)
    for item in items:
        by_cost[item.get('cost_item', '')].append(item.get('amount'))
    for name, amounts in by_cost.items():
        if all(a is None for a in amounts):
            issues.append(('WARN', f'费用项目 "{name}" 所有 {len(amounts)} 条 amount 均为空'))

    return issues


def check_subsection(data, page):
    """校验小节标题。

    WARN: subsection 为空（非续表页）
    """
    issues = []
    sub = data.get('subsection', '')
    if not sub:
        # 可能是续表，也可能是漏提取
        issues.append(('WARN', 'subsection 为空'))
    return issues


# ─── 汇总 ───

ALL_CHECKS = [
    ('cost_items', check_cost_items),
    ('attr_dimensions', check_attr_dimensions),
    ('work_content', check_work_content),
    ('norms_codes', check_norms_codes),
    ('item_counts', check_item_counts),
    ('subsection', check_subsection),
]


def validate_page(pg):
    """校验单页，返回 (page, issues)"""
    fpath = EXTRACTED_DIR / f"page_{pg:04d}.json"
    if not fpath.exists():
        return pg, [('SKIP', '文件不存在')]

    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not data.get('items'):
        return pg, [('SKIP', '无 items（非定额表页）')]

    all_issues = []
    for check_name, check_fn in ALL_CHECKS:
        try:
            issues = check_fn(data, pg)
            for level, msg in issues:
                all_issues.append((level, f'[{check_name}] {msg}'))
        except Exception as e:
            all_issues.append(('ERROR', f'[{check_name}] 校验异常: {e}'))

    return pg, all_issues


def validate_db(db_path):
    """校验已入库的SQLite数据。"""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    issues_by_page = defaultdict(list)

    # Check 1: cost_item 是纯单位
    for row in conn.execute(
        "SELECT DISTINCT page, cost_item, COUNT(*) as cnt FROM norms_item "
        "WHERE cost_item IN ({}) GROUP BY page, cost_item ORDER BY page"
        .format(','.join('?' for _ in UNIT_WORDS)), list(UNIT_WORDS)
    ):
        issues_by_page[row['page']].append(
            ('FATAL', f'[cost_items] {row["cnt"]} 条 cost_item="{row["cost_item"]}"（纯单位词）'))

    # Check 2: attr_dimensions 为空
    for row in conn.execute(
        "SELECT nt.page, COUNT(DISTINCT ni.norms_code) as n_codes "
        "FROM norms_table nt JOIN norms_item ni ON nt.id = ni.table_id "
        "WHERE nt.header_json LIKE '%\"attr_dimensions\": []%' "
        "   OR nt.header_json NOT LIKE '%attr_dimensions%' "
        "GROUP BY nt.page"
    ):
        if row['n_codes'] > 1:
            issues_by_page[row['page']].append(
                ('WARN', f'[attr_dimensions] {row["n_codes"]} 个定额编号但 attr_dimensions 为空'))

    # Check 3: item count mismatch
    for row in conn.execute(
        "SELECT nt.page, nt.row_count as actual, "
        "       (SELECT COUNT(DISTINCT ni.cost_item) FROM norms_item ni WHERE ni.table_id = nt.id) as n_ci, "
        "       (SELECT COUNT(DISTINCT ni.norms_code) FROM norms_item ni WHERE ni.table_id = nt.id) as n_codes "
        "FROM norms_table nt "
        "WHERE nt.row_count != (SELECT COUNT(DISTINCT ni.cost_item) FROM norms_item ni WHERE ni.table_id = nt.id) "
        "   * (SELECT COUNT(DISTINCT ni.norms_code) FROM norms_item ni WHERE ni.table_id = nt.id)"
    ):
        expected = row['n_ci'] * row['n_codes']
        issues_by_page[row['page']].append(
            ('ERROR', f'[item_counts] 实际 {row["actual"]} != 期望 {expected} ({row["n_ci"]}费用×{row["n_codes"]}编号)'))

    conn.close()
    return issues_by_page


# ─── 报告 ───

def print_report(results, title="校验报告"):
    """打印校验报告。results = [(page, [(level, msg), ...]), ...]"""

    by_level = defaultdict(list)
    total_ok = 0
    for pg, issues in results:
        if not issues:
            total_ok += 1
            continue
        for level, msg in issues:
            by_level[level].append((pg, msg))

    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"  校验页面: {len(results)}")
    print(f"  通过: {total_ok}")
    print(f"  FATAL: {len(by_level.get('FATAL',[]))}  ERROR: {len(by_level.get('ERROR',[]))}  "
          f"WARN: {len(by_level.get('WARN',[]))}  SKIP: {len(by_level.get('SKIP',[]))}")

    for level in ('FATAL', 'ERROR', 'WARN'):
        items = by_level.get(level, [])
        if not items:
            continue
        print(f"\n  --- {level} ({len(items)}) ---")
        # Group by page
        by_page = defaultdict(list)
        for pg, msg in items:
            by_page[pg].append(msg)
        for pg in sorted(by_page.keys()):
            for msg in by_page[pg]:
                print(f"    P{pg:4d}: {msg}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('pages', nargs='?', help='页码或范围 (如 155 或 140-180)')
    parser.add_argument('--db', action='store_true', help='校验已入库的DB而非extracted JSON')
    parser.add_argument('--db-path',
                        default=str(ROOT / 'output' / 'db' / 'JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite'),
                        help='DB路径')
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db_path)
        if not db_path.exists():
            print(f"DB not found: {db_path}")
            sys.exit(1)
        issues_by_page = validate_db(db_path)
        results = [(pg, issues_by_page.get(pg, [])) for pg in sorted(issues_by_page.keys())]
        print_report(results, f"DB校验: {db_path.name}")
        return

    if args.pages:
        if '-' in args.pages:
            start, end = args.pages.split('-')
            pages = list(range(int(start), int(end) + 1))
        else:
            pages = [int(args.pages)]
    else:
        pages = sorted(
            int(re.match(r'page_(\d+)\.json', f.name).group(1))
            for f in EXTRACTED_DIR.glob('page_*.json')
            if re.match(r'page_(\d+)\.json', f.name)
        )

    results = []
    for pg in pages:
        pg, issues = validate_page(pg)
        results.append((pg, issues))
        if len(results) % 100 == 0:
            print(f"  ... {len(results)}/{len(pages)}")

    print_report(results, f"提取结果校验: {len(pages)} 页")


if __name__ == '__main__':
    main()
