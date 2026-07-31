"""Validate markdown norms files for completeness and consistency.

Usage:
    python scripts/verify_md.py [--pages 29-60] [--strict]
"""

import sys
import re
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import MD_DIR, GOLD_SET_PAGES


def parse_frontmatter(text):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).strip().split('\n'):
        kv = line.split(':', 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip()
            try:
                val = int(val)
            except ValueError:
                pass
            fm[key] = val
    return fm


def check_md_file(path, skip_jijia=False):
    """Check a single markdown file. Returns list of issues."""
    issues = []
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    fm = parse_frontmatter(text)
    page = fm.get('page', 0)

    # Check frontmatter
    if not fm.get('chapter'):
        issues.append(f"Missing chapter in frontmatter")
    if not fm.get('section'):
        issues.append(f"Missing section in frontmatter")
    if fm.get('type') != 'norms_table':
        issues.append(f"Unexpected type: {fm.get('type')}")

    # Find all table rows
    data_rows = []
    for line in text.split('\n'):
        if line.startswith('|') and not line.startswith('|:') and '---' not in line:
            cells = [c.strip() for c in line.split('|')[1:-1]]
            if cells and cells[0].replace(' ', '').replace('定额编号', ''):
                if cells[0].isdigit():
                    data_rows.append(cells)

    if not data_rows:
        issues.append("No data rows found")
        return issues

    # Check norms codes
    codes_seen = set()
    for row in data_rows:
        code = row[0]
        if not code.isdigit():
            pass  # skip non-numeric
        elif code in codes_seen:
            pass  # duplicates expected (one per cost item)
        else:
            codes_seen.add(code)

    codes_sorted = sorted(codes_seen, key=int)
    if len(codes_sorted) > 1:
        # Check continuity
        first, last = int(codes_sorted[0]), int(codes_sorted[-1])
        expected = set(str(i) for i in range(first, last + 1))
        missing = expected - codes_seen
        extra = codes_seen - expected
        if missing:
            issues.append(f"Missing codes between {first} and {last}: {sorted(missing, key=int)}")
        if extra:
            issues.append(f"Extra codes outside range {first}-{last}: {sorted(extra, key=int)}")

    # Check cost items
    items_per_code = defaultdict(set)
    for row in data_rows:
        if len(row) >= 6:
            items_per_code[row[0]].add(row[-3])  # cost item column

    # Verify each code has 基价 (skip for first pages of multi-page sections)
    if not skip_jijia:
        for code in codes_seen:
            if '基价' not in items_per_code[code]:
                issues.append(f"Code {code} missing 基价 row")

    # Summary
    n_codes = len(codes_seen)
    n_rows = len(data_rows)
    issues.insert(0, f"OK: {n_codes} codes, {n_rows} rows")

    return issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Verify markdown norms files')
    parser.add_argument('--pages', help='Comma-separated page numbers or range')
    parser.add_argument('--md-dir', default=str(MD_DIR), help='Markdown directory')
    parser.add_argument('--strict', action='store_true', help='Treat warnings as errors')
    parser.add_argument('--gold-set', action='store_true', help='Only check gold set pages')
    args = parser.parse_args()

    md_dir = Path(args.md_dir)

    if args.gold_set:
        pages = set(GOLD_SET_PAGES)
        md_files = [md_dir / f'page_{p:04d}.md' for p in GOLD_SET_PAGES]
        md_files = [f for f in md_files if f.exists()]
    elif args.pages:
        pages = set()
        for part in args.pages.split(','):
            part = part.strip()
            if '-' in part:
                a, b = part.split('-', 1)
                pages.update(range(int(a), int(b) + 1))
            else:
                pages.add(int(part))
        md_files = sorted(md_dir.glob('page_*.md'))
        md_files = [f for f in md_files if int(f.stem.split('_')[1]) in pages]
    else:
        md_files = sorted(md_dir.glob('page_*.md'))

    if not md_files:
        print("No markdown files found")
        return 1

    # Build set of pages that are first pages of multi-page sections
    # (these won't have 基价 rows — they appear on the continuation page)
    skip_jijia_pages = set()
    for md_path in md_files:
        fm = parse_frontmatter(md_path.read_text(encoding='utf-8'))
        cf = fm.get('continued_from')
        if cf is not None and isinstance(cf, int):
            skip_jijia_pages.add(cf)

    total_issues = 0
    total_codes = 0
    total_rows = 0

    for md_path in md_files:
        page_num = int(md_path.stem.split('_')[1])
        issues = check_md_file(md_path, skip_jijia=(page_num in skip_jijia_pages))
        has_real_issues = any(not i.startswith('OK:') for i in issues)
        status = 'ERROR' if has_real_issues else 'OK'
        print(f"\n{status} {md_path.name}:")
        for issue in issues:
            if issue.startswith('OK:'):
                parts = issue.split(':')
                stats = parts[1].strip().split(',')
                total_codes += int(stats[0].split()[0])
                total_rows += int(stats[1].split()[0])
            else:
                total_issues += 1
                print(f"  - {issue}")

    print(f"\n--- Summary ---")
    print(f"Files: {len(md_files)}")
    print(f"Total codes: {total_codes}")
    print(f"Total rows: {total_rows}")
    print(f"Issues: {total_issues}")
    return 0 if total_issues == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
