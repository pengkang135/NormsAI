#!/usr/bin/env python3
"""Deterministic column clustering from text+coordinate JSON.
Outputs column-aligned data ready for AI semantic extraction.

Usage:
  python scripts/cluster_columns.py              # all pages
  python scripts/cluster_columns.py 97           # single page
  python scripts/cluster_columns.py 90-100       # range
"""

import json, sys, re, os, io
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
TEXT_DIR = ROOT / "output" / "intermediate" / "text"
STRUCTURE_PATH = ROOT / "output" / "structure_full.json"
OUT_DIR = ROOT / "output" / "intermediate" / "clustered"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NOISE_RE = re.compile(r'^-\s*\d+\s*-$|^-\s*\d+\s*\.\s*\d+\s*-$')
META_TEXTS = {"定额编号", "项目", "单位", "代码", "顺", "序", "号", "顺序", "序号", "编号", "续表"}
UNIT_PATTERNS = {"工日", "m³", "m²", "㎡", "元", "%", "kg", "t", "m",
                 "个", "套", "艘", "台", "班", "只", "km", "樘", "块",
                 "根", "件", "片", "组", "条", "座", "处", "10m³", "10m",
                 "组日", "艘班", "台班", "延长米", "100m³", "100m²", "10m",
                 "榀", "段"}


def is_noise(t):
    return bool(NOISE_RE.match(t)) or t in ("·", ".", "..", "...")


def group_by_y(lines, tolerance=5):
    groups = []
    for line in sorted(lines, key=lambda l: (l["y"], l["x"])):
        placed = False
        for grp in groups:
            if abs(grp[0]["y"] - line["y"]) <= tolerance:
                grp.append(line)
                placed = True
                break
        if not placed:
            groups.append([line])
    for grp in groups:
        grp.sort(key=lambda l: l["x"])
    groups.sort(key=lambda g: g[0]["y"])
    return groups


def cluster_page(pg):
    """Cluster one page: identify columns, rows, metadata."""
    fpath = TEXT_DIR / f"page_{pg:04d}.json"
    if not fpath.exists():
        return None

    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    lines = data["lines"]
    clean_lines = [l for l in lines if l["text"].strip() and not is_noise(l["text"].strip())]
    rows = group_by_y(clean_lines)
    if not rows:
        return None

    # --- Metadata ---
    subsection = ""
    work_content = ""
    unit = ""

    for grp in rows[:8]:
        texts = [l["text"].strip() for l in grp]
        combined = "".join(texts)

        if re.match(r'^[一二三四五六七八九十]+、', combined) and not subsection:
            subsection = combined
        elif re.match(r'^\d{1,2}[\.、]\s*\S', combined) and not subsection:
            subsection = combined
        elif "工程内容" in combined:
            wc = combined
            for marker in ["工程内容：", "工作内容："]:
                if marker in wc:
                    wc = wc[wc.index(marker) + len(marker):]
            work_content = wc.strip()

        UNIT_RE = re.compile(
            r'^\d+\s*(m[³3²2]|根|件|个|m²|㎡|m³|m|t|kg|km|%|元|工日|10m|100m|'
            r'10\s*根|10\s*件|10m\s*桩|100m²|10m³|10\s*个|100\s*个)')
        for l in grp:
            t = l["text"].strip()
            if UNIT_RE.match(t) and len(t) < 20:
                if not unit or len(t) < len(unit):
                    unit = t

    # --- Find norms codes row ---
    code_row_idx = None
    for i, grp in enumerate(rows):
        if any(re.match(r'^\d{5}$', l["text"].strip()) for l in grp):
            code_row_idx = i
            break

    if code_row_idx is None:
        return None

    # --- Detect continued table ---
    has_continued = any("续表" in l["text"] and len(l["text"].strip()) < 20
                        for r in rows[:3] for l in r)
    has_norms_header = any("定额编号" in l["text"] for r in rows for l in r)
    is_continued = has_continued and not has_norms_header

    # --- Parse norms codes ---
    norms_codes = []
    for l in rows[code_row_idx]:
        t = l["text"].strip()
        if re.match(r'^\d{5}$', t):
            norms_codes.append({"code": t, "x": l["x"]})

    if not norms_codes:
        return None

    n = len(norms_codes)
    code_xs = [c["x"] for c in norms_codes]

    # Column boundaries
    col_left = []
    col_right = []
    for i in range(n):
        if i == 0:
            left = code_xs[0] - (code_xs[1] - code_xs[0]) / 2 if n > 1 else code_xs[0] - 60
        else:
            left = (code_xs[i-1] + code_xs[i]) / 2
        if i < n - 1:
            right = (code_xs[i] + code_xs[i+1]) / 2
        else:
            right = code_xs[-1] + (code_xs[-1] - code_xs[-2]) / 2 if n > 1 else code_xs[0] + 60
        col_left.append(left)
        col_right.append(right)

    # --- Determine header range ---
    header_start = code_row_idx
    for i in range(code_row_idx - 1, max(code_row_idx - 12, -1), -1):
        grp = rows[i]
        texts = [l["text"].strip() for l in grp]
        has_only_meta = all(
            t in META_TEXTS or re.match(r'^\d{1,3}$', t) or re.match(r'^续前表$', t)
            for t in texts if t)
        if has_only_meta:
            continue
        if any("工程内容" in t for t in texts):
            break
        if any(re.match(r'^[一二三四五六七八九十]+、', t) for t in texts):
            break
        cleaned = [t for t in texts if t and not is_noise(t)]
        has_chinese = any(re.search(r'[一-鿿]', t) for t in cleaned)
        if has_chinese:
            header_start = min(header_start, i)

    header_end = code_row_idx
    for i in range(code_row_idx + 1, len(rows)):
        grp = rows[i]
        texts = [l["text"].strip() for l in grp]
        cleaned = [t for t in texts if t and not is_noise(t)]
        if not cleaned:
            continue
        # Stop at sequence numbers (data rows)
        if re.match(r'^\d{1,3}$', cleaned[0]) and i > code_row_idx + 2:
            # Verify this is really a data row, not a numeric attribute in header
            if int(cleaned[0]) <= 50:
                break
        header_end = i

    # --- Collect column header texts ---
    for ci in range(n):
        norms_codes[ci]["header_texts"] = []

    for i in range(header_start, header_end + 1):
        if i == code_row_idx:
            continue
        for l in rows[i]:
            t = l["text"].strip()
            if not t or is_noise(t):
                continue
            if t in META_TEXTS:
                continue
            if re.match(r'^\d{1,3}$', t) and l["x"] < 150:
                continue
            if re.match(r'^续前表$', t):
                continue
            if re.match(r'^\d{5}$', t):
                continue

            # Assign to column by x
            for ci in range(n):
                if col_left[ci] <= l["x"] < col_right[ci]:
                    norms_codes[ci]["header_texts"].append({"text": t, "y": round(l["y"], 1)})
                    break

    # --- Find data rows ---
    data_rows_raw = []
    for i in range(header_end + 1, len(rows)):
        grp = rows[i]
        texts = [l["text"].strip() for l in grp if l["text"].strip() and not is_noise(l["text"].strip())]
        if not texts:
            continue
        if re.match(r'^\d{1,3}$', texts[0]) and int(texts[0]) < 100:
            data_rows_raw.append(grp)

    # --- Extract cost items and data ---
    cost_items_seen = {}
    cost_items = []
    data_rows = []

    for grp in data_rows_raw:
        texts = [l["text"].strip() for l in grp]
        if len(texts) < 2:
            continue

        name = texts[1]
        if not name or re.match(r'^[\d\.\-\sⅠⅡⅢⅣⅤ]+$', name):
            continue
        if name in UNIT_PATTERNS:
            continue

        item_unit = ""
        code_val = ""
        for l in grp:
            t = l["text"].strip()
            if re.match(r'^\d{10,}$', t) and not code_val:
                code_val = t
            elif t in UNIT_PATTERNS and not item_unit:
                item_unit = t

        key = (name, item_unit)
        if key not in cost_items_seen:
            ci = {"name": name, "unit": item_unit, "code": code_val}
            cost_items_seen[key] = len(cost_items)
            cost_items.append(ci)

        # Match values to code columns (closest column wins)
        values = {}
        for l in grp:
            t = l["text"].strip()
            if re.match(r'^-?\d+\.?\d*$', t):
                val = float(t)
                best_ci = min(range(n), key=lambda ci: abs(l["x"] - norms_codes[ci]["x"]))
                if abs(l["x"] - norms_codes[best_ci]["x"]) < 100:
                    values[norms_codes[best_ci]["code"]] = val
            elif t in ("－", "—", "---"):
                best_ci = min(range(n), key=lambda ci: abs(l["x"] - norms_codes[ci]["x"]))
                if abs(l["x"] - norms_codes[best_ci]["x"]) < 100:
                    values[norms_codes[best_ci]["code"]] = None

        data_rows.append({
            "name": name,
            "unit": item_unit,
            "code": code_val,
            "values": values,
        })

    if not data_rows:
        return None

    return {
        "page": pg,
        "subsection": subsection,
        "work_content": work_content,
        "unit": unit,
        "is_continued": is_continued,
        "code_columns": [{k: v for k, v in nc.items() if k != "x"} for nc in norms_codes],
        "cost_items": cost_items,
        "data_rows": data_rows,
    }


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if '-' in arg:
            start, end = arg.split('-')
            pages = list(range(int(start), int(end) + 1))
        else:
            pages = [int(arg)]
    else:
        pages = []
        for fpath in sorted(TEXT_DIR.glob("page_*.json")):
            m = re.match(r'page_(\d+)\.json', fpath.name)
            if m:
                pages.append(int(m.group(1)))

    clustered = 0
    skipped = 0
    for pg in sorted(pages):
        result = cluster_page(pg)
        if result:
            out_path = OUT_DIR / f"page_{pg:04d}.json"
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            clustered += 1
        else:
            skipped += 1

    print(f"Clustered: {clustered} pages")
    print(f"Skipped (non-table): {skipped}")
    print(f"Output: {OUT_DIR}")


if __name__ == '__main__':
    main()
