#!/usr/bin/env python
"""导入 PK 土建定额库 Excel → SQLite BOQ 数据库 (v2 — 含消耗量).

四级编码体系:
  L1 Section:   [A-V]      → 【土石方工程】
  L2 Sub-section: X.x      → 《土石方》
  L3 Group:      X.x.NN    → {喷射注浆}
  L4 Item:       X.x.NN.NNN → 场地机械平整

列结构 (A-Z):
  A: 编码  B: 项目名称  C: 单位  D: 项目特征  E: 分类指标
  F: 工作内容  G: 计算规则  H: 英文名称
  I: 成本合价  J: 工程量  K: 单价  L: 人工  M: 材料  N: 机械
  O-Z: 消耗量1-12 (资源名称定义在subsection行, 单价在下一行)

用法:
  python import_boq_library.py "input.xlsx"
  python import_boq_library.py "input.xlsx" --db custom.sqlite
"""

import argparse
import re
import sqlite3
import sys
import zipfile
from pathlib import Path
from defusedxml import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# ── XML parsing ──────────────────────────────────────────────

def load_shared_strings(zf):
    """Load shared strings from xl/sharedStrings.xml."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    with zf.open("xl/sharedStrings.xml") as f:
        tree = ET.parse(f)
    strings = []
    for si in tree.findall(f"{{{NS}}}si"):
        t = si.find(f"{{{NS}}}t")
        strings.append(t.text if t is not None and t.text else "")
    return strings


def parse_cell_value(c_elem, strings):
    """Extract value from a shared-string, inlineStr, or numeric cell."""
    t = c_elem.get("t", "")
    # Shared string: <c t="s"><v>index</v></c>
    if t == "s":
        v = c_elem.find(f"{{{NS}}}v")
        if v is not None and v.text:
            idx = int(v.text)
            return strings[idx] if 0 <= idx < len(strings) else None
        return None
    # Inline string: <c t="inlineStr"><is><t>text</t></is></c>
    if t == "inlineStr":
        is_elem = c_elem.find(f"{{{NS}}}is")
        if is_elem is not None:
            parts = []
            for t_elem in is_elem.findall(f".//{{{NS}}}t"):
                if t_elem.text:
                    parts.append(t_elem.text)
            return "".join(parts) or None
        return None
    # Numeric / boolean: <c><v>value</v></c>
    v = c_elem.find(f"{{{NS}}}v")
    if v is not None and v.text:
        return v.text
    return None


def col_ref_to_letter(ref):
    return re.match(r"([A-Z]+)", ref).group(1) if ref else ""


def safe_float(val):
    """Convert string to float, return None on failure."""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def parse_sheet(xlsx_path):
    """Parse xlsx sheet, returning (rows, resource_defs_by_subsection)."""
    rows = []
    resource_defs = {}  # subsection_code -> list of {col, name, unit, unit_price}

    with zipfile.ZipFile(xlsx_path, "r") as z:
        strings = load_shared_strings(z)
        with z.open("xl/worksheets/sheet1.xml") as f:
            tree = ET.parse(f)

        prev_sub_code = None

        for row_elem in tree.findall(f".//{{{NS}}}row"):
            r = int(row_elem.get("r"))
            if r <= 2:  # skip header rows
                continue

            cells = {}
            for c in row_elem.findall(f"{{{NS}}}c"):
                col = col_ref_to_letter(c.get("r"))
                val = parse_cell_value(c, strings)
                cells[col] = val

            code = cells.get("A", "")

            # Detect subsection header row (code = X.x) — may define resources in O-Z
            if code and re.match(r"^[A-Z]\.[a-z]$", str(code)):
                prev_sub_code = code
                # Check if O-Z columns contain resource definitions (name\nunit format)
                resources = []
                for col_letter in "OPQRSTUVWXYZ":
                    v = cells.get(col_letter, "")
                    if v and "\n" in str(v):
                        parts = str(v).split("\n")
                        name = parts[0].strip()
                        unit = parts[1].strip() if len(parts) > 1 else ""
                        resources.append({
                            "col": col_letter,
                            "name": name,
                            "unit": unit,
                            "unit_price": None,
                        })
                if resources:
                    resource_defs[code] = resources

            # Detect unit-price row (next row after resource def, no code, has numeric O-Z)
            if not code and prev_sub_code and prev_sub_code in resource_defs:
                resources = resource_defs[prev_sub_code]
                has_prices = False
                for res in resources:
                    price_val = cells.get(res["col"])
                    price = safe_float(price_val)
                    if price is not None:
                        res["unit_price"] = price
                        has_prices = True
                if has_prices:
                    prev_sub_code = None  # consumed the price row

            # Only keep rows with an A-column code
            if code:
                rows.append({"row": r, **cells})

    return rows, resource_defs


# ── Code classification ─────────────────────────────────────

def classify_code(code):
    if not code:
        return None
    if re.match(r"^[A-Z]$", code):
        return (1, "section")
    if re.match(r"^[A-Z]\.[a-z]$", code):
        return (2, "subsection")
    if re.match(r"^[A-Z]\.[a-z]\.\d+$", code):
        return (3, "group")
    if re.match(r"^[A-Z]\.[a-z]\.\d+\.\d+$", code):
        return (4, "item")
    return None


# ── Bracket stripping ────────────────────────────────────────

def strip_brackets(text):
    if not text:
        return "", None
    t = text.strip()
    if t.startswith("【") and t.endswith("】"):
        return t[1:-1], "section"
    if t.startswith("《") and t.endswith("》"):
        return t[1:-1], "subsection"
    if t.startswith("{") and t.endswith("}"):
        return t[1:-1], "group"
    return t, None


def clean_text(text):
    if not text:
        return ""
    return text.replace("​", "").replace("‌", "").replace("‍", "").strip()


# ── Hierarchy builder ────────────────────────────────────────

def build_hierarchy(rows):
    sections = []
    subsections = []
    groups = {}
    items = []

    for row in rows:
        code = clean_text(row.get("A", ""))
        cls = classify_code(code)
        if cls is None:
            continue
        level, cat = cls
        name = clean_text(row.get("B", ""))
        name_en = clean_text(row.get("H", ""))

        if cat == "section":
            title, btype = strip_brackets(name)
            title_en, _ = strip_brackets(name_en)
            sections.append((code, title, title_en, btype))
        elif cat == "subsection":
            title, btype = strip_brackets(name)
            title_en, _ = strip_brackets(name_en)
            subsections.append((code, title, title_en, btype))
        elif cat == "group":
            title, btype = strip_brackets(name)
            title_en, _ = strip_brackets(name_en)
            groups[code] = (title, title_en, btype)
        elif cat == "item":
            items.append({
                "code": code,
                "name": name,
                "unit": clean_text(row.get("C", "")),
                "description": clean_text(row.get("D", "")),
                "type": clean_text(row.get("E", "")),
                "work_content": clean_text(row.get("F", "")),
                "calc_rule": clean_text(row.get("G", "")),
                "name_en": name_en,
                "amount": safe_float(row.get("I")),
                "quantity": safe_float(row.get("J")),
                "rate": safe_float(row.get("K")),
                "labour": safe_float(row.get("L")),
                "materials": safe_float(row.get("M")),
                "mech": safe_float(row.get("N")),
                "consumption": _parse_consumption(row),
            })

    # Detect implicit groups
    explicit_group_codes = set(groups.keys())
    needed_groups = set()
    for item in items:
        parts = item["code"].split(".")
        parent_code = ".".join(parts[:3])
        if parent_code not in explicit_group_codes:
            needed_groups.add(parent_code)

    for code in sorted(needed_groups):
        groups[code] = ("", "", None)

    return sections, subsections, groups, items, needed_groups


def _parse_consumption(row):
    """Extract consumption quantities from O-Z columns. Returns dict col->float or None."""
    cons = {}
    for col in "OPQRSTUVWXYZ":
        val = row.get(col)
        f = safe_float(val)
        if f is not None and f != 0:
            cons[col] = f
    return cons if cons else None


# ── SQLite writer ────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES chapter(id),
    sort_order INTEGER,
    level INTEGER,
    title TEXT NOT NULL,
    subtitle TEXT,
    code TEXT,
    bracket_type TEXT,
    is_implicit INTEGER DEFAULT 0,
    toc_page INTEGER DEFAULT 0,
    start_page INTEGER DEFAULT 0,
    end_page INTEGER DEFAULT 0,
    is_appendix INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS boq_item (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id),
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    name_en TEXT,
    unit TEXT,
    description TEXT,
    type TEXT,
    work_content TEXT,
    calc_rule TEXT,
    sort_order INTEGER,
    amount REAL,
    quantity REAL,
    rate REAL,
    labour REAL,
    materials REAL,
    mech REAL
);

CREATE TABLE IF NOT EXISTS boq_resource_def (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER REFERENCES chapter(id),
    col_letter TEXT NOT NULL,
    sort_order INTEGER,
    resource_name TEXT NOT NULL,
    resource_unit TEXT,
    unit_price REAL
);

CREATE TABLE IF NOT EXISTS boq_resource_qty (
    id INTEGER PRIMARY KEY,
    item_id INTEGER REFERENCES boq_item(id),
    resource_def_id INTEGER REFERENCES boq_resource_def(id),
    consumption REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_boq_item_code ON boq_item(code);
CREATE INDEX IF NOT EXISTS idx_boq_item_chapter ON boq_item(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chapter_code ON chapter(code);
CREATE INDEX IF NOT EXISTS idx_chapter_parent ON chapter(parent_id);
CREATE INDEX IF NOT EXISTS idx_boq_resdef_chapter ON boq_resource_def(chapter_id);
CREATE INDEX IF NOT EXISTS idx_boq_resqty_item ON boq_resource_qty(item_id);
"""

# ── Compatibility layer for Norms-AI browser ─────────────────

COMPAT_DDL = """
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    doc_number TEXT,
    publisher TEXT,
    effective_date TEXT,
    total_pages INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS page_index (
    page INTEGER PRIMARY KEY,
    page_type TEXT NOT NULL,
    chapter_id INTEGER,
    table_id INTEGER,
    appendix_id INTEGER,
    text_preview TEXT,
    ocr_status TEXT,
    ocr_lines INTEGER,
    ocr_confidence REAL
);

CREATE TABLE IF NOT EXISTS norms_table (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER,
    section_title TEXT,
    subsection_title TEXT,
    subsection_clean TEXT,
    work_content TEXT,
    unit TEXT,
    page INTEGER,
    seq_on_page INTEGER,
    header_json TEXT,
    row_count INTEGER,
    col_count INTEGER
);

CREATE TABLE IF NOT EXISTS norms_item (
    id INTEGER PRIMARY KEY,
    table_id INTEGER,
    page INTEGER,
    norms_code TEXT NOT NULL,
    sort_order INTEGER,
    attr_level1 TEXT,
    attr_level2 TEXT,
    attr_level3 TEXT,
    attr_level4 TEXT,
    attr1_label TEXT,
    attr2_label TEXT,
    attr3_label TEXT,
    attr4_label TEXT,
    cost_item TEXT NOT NULL,
    cost_item_unit TEXT,
    amount REAL,
    ocr_source TEXT,
    data_quality TEXT
);

CREATE INDEX IF NOT EXISTS idx_norms_code ON norms_item(norms_code);
CREATE INDEX IF NOT EXISTS idx_norms_table ON norms_item(table_id);
CREATE INDEX IF NOT EXISTS idx_page_type ON page_index(page_type);
"""


def write_compatibility_layer(db, sections, subsections, groups, items, resource_defs):
    import json
    from collections import Counter

    group_map = {}
    for row in db.execute("SELECT code, id, title FROM chapter WHERE level=3 ORDER BY sort_order"):
        group_map[row["code"]] = (row["id"], row["title"])

    sub_map = {}
    for row in db.execute("SELECT code, title FROM chapter WHERE level=2"):
        sub_map[row["code"]] = row["title"]

    # Build items-by-group
    items_by_group = {}
    for item in items:
        parts = item["code"].split(".")
        group_code = ".".join(parts[:3])
        items_by_group.setdefault(group_code, []).append(item)

    # Build resource def lookup: subsection_code -> list of defs
    # We stored resource_defs keyed by subsection code
    # Need a mapping: group_code -> subsection_code
    group_to_sub = {}
    for gcode in items_by_group:
        parts = gcode.split(".")
        sub_code = ".".join(parts[:2])
        group_to_sub[gcode] = sub_code

    db.execute(
        "INSERT INTO document (title, doc_number, total_pages, created_at) VALUES (?, ?, ?, datetime('now'))",
        ("PK土建定额库 2026.06", "", len(groups)),
    )

    table_ids = {}
    page_base = 10000

    for sort_idx, (group_code, group_items) in enumerate(sorted(items_by_group.items()), 1):
        chapter_id, group_title = group_map.get(group_code, (None, ""))
        if chapter_id is None:
            continue

        parts = group_code.split(".")
        sub_code = ".".join(parts[:2])
        section_title = sub_map.get(sub_code) or sub_code

        units = [it["unit"] for it in group_items if it["unit"]]
        unique_units = list(dict.fromkeys(units))
        common_unit = ", ".join(unique_units) if len(unique_units) <= 3 else ""

        work_content = ""
        for it in group_items:
            if it["work_content"]:
                work_content = it["work_content"][:200]
                break

        page = page_base + sort_idx
        header_json = json.dumps(
            {
                "columns": ["定额编号", "分类指标", "项目特征", "工作内容", "计算规则",
                            "成本合价", "工程量", "单价", "人工", "材料", "机械"],
                "labels": {
                    "attr1_label": "分类指标",
                    "attr2_label": "项目特征",
                    "attr3_label": "工作内容",
                    "attr4_label": "计算规则",
                },
            },
            ensure_ascii=False,
        )

        c = db.execute(
            """INSERT INTO norms_table (chapter_id, section_title, subsection_title, work_content, unit, page, seq_on_page, header_json, row_count, col_count)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 6)""",
            (chapter_id, section_title, group_title or group_code, work_content, common_unit, page, header_json,
             len(group_items)),
        )
        table_id = c.lastrowid
        table_ids[group_code] = table_id

        db.execute(
            "INSERT INTO page_index (page, page_type, chapter_id, table_id, text_preview) VALUES (?, 'norms_table', ?, ?, ?)",
            (page, chapter_id, table_id, f"{group_code} ({len(group_items)}项)"),
        )

    # Insert norms_item — including cost breakdown and resource consumption
    for group_code, group_items in items_by_group.items():
        table_id = table_ids.get(group_code)
        if table_id is None:
            continue

        sub_code = group_to_sub.get(group_code, "")
        sub_resources = resource_defs.get(sub_code, [])

        for item in group_items:
            parts = item["code"].split(".")
            try:
                item_sort = int(parts[3])
            except (ValueError, IndexError):
                item_sort = 0

            # --- Row 1: 人工 (labour cost) ---
            if item.get("labour") is not None and item["labour"] != 0:
                db.execute(
                    """INSERT INTO norms_item (table_id, norms_code, sort_order,
                       attr_level1, attr_level2, attr_level3, attr_level4,
                       attr1_label, attr2_label, attr3_label, attr4_label,
                       cost_item, cost_item_unit, amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (table_id, item["code"], item_sort,
                     item["type"] or "", item["description"] or "",
                     item["work_content"][:100] if item["work_content"] else "",
                     item["calc_rule"][:100] if item["calc_rule"] else "",
                     "分类指标", "项目特征", "工作内容", "计算规则",
                     "人工费", "元", item["labour"]),
                )

            # --- Row 2: 材料 (materials cost) ---
            if item.get("materials") is not None and item["materials"] != 0:
                db.execute(
                    """INSERT INTO norms_item (table_id, norms_code, sort_order,
                       attr_level1, attr_level2, attr_level3, attr_level4,
                       attr1_label, attr2_label, attr3_label, attr4_label,
                       cost_item, cost_item_unit, amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (table_id, item["code"], item_sort,
                     item["type"] or "", item["description"] or "",
                     item["work_content"][:100] if item["work_content"] else "",
                     item["calc_rule"][:100] if item["calc_rule"] else "",
                     "分类指标", "项目特征", "工作内容", "计算规则",
                     "材料费", "元", item["materials"]),
                )

            # --- Row 3: 机械 (machinery cost) ---
            if item.get("mech") is not None and item["mech"] != 0:
                db.execute(
                    """INSERT INTO norms_item (table_id, norms_code, sort_order,
                       attr_level1, attr_level2, attr_level3, attr_level4,
                       attr1_label, attr2_label, attr3_label, attr4_label,
                       cost_item, cost_item_unit, amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (table_id, item["code"], item_sort,
                     item["type"] or "", item["description"] or "",
                     item["work_content"][:100] if item["work_content"] else "",
                     item["calc_rule"][:100] if item["calc_rule"] else "",
                     "分类指标", "项目特征", "工作内容", "计算规则",
                     "机械费", "元", item["mech"]),
                )

            # --- Row 4: 单价 (unit rate, as base cost item) ---
            if item.get("rate") is not None:
                db.execute(
                    """INSERT INTO norms_item (table_id, norms_code, sort_order,
                       attr_level1, attr_level2, attr_level3, attr_level4,
                       attr1_label, attr2_label, attr3_label, attr4_label,
                       cost_item, cost_item_unit, amount)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (table_id, item["code"], item_sort,
                     item["type"] or "", item["description"] or "",
                     item["work_content"][:100] if item["work_content"] else "",
                     item["calc_rule"][:100] if item["calc_rule"] else "",
                     "分类指标", "项目特征", "工作内容", "计算规则",
                     item["name"], item["unit"] or "", item["rate"]),
                )

            # --- Resource consumption rows ---
            if item.get("consumption"):
                for col_letter, qty in item["consumption"].items():
                    # Find resource name from subsection definitions
                    res_name = f"消耗量({col_letter})"
                    res_unit = ""
                    for rd in sub_resources:
                        if rd["col"] == col_letter:
                            res_name = rd["name"]
                            res_unit = rd["unit"]
                            break
                    db.execute(
                        """INSERT INTO norms_item (table_id, norms_code, sort_order,
                           attr_level1, attr_level2, attr_level3, attr_level4,
                           attr1_label, attr2_label, attr3_label, attr4_label,
                           cost_item, cost_item_unit, amount)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (table_id, item["code"], item_sort,
                         item["type"] or "", item["description"] or "",
                         item["work_content"][:100] if item["work_content"] else "",
                         item["calc_rule"][:100] if item["calc_rule"] else "",
                         "分类指标", "项目特征", "工作内容", "计算规则",
                         res_name, res_unit, qty),
                    )


def write_db(db_path, sections, subsections, groups, items, implicit_codes, resource_defs):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.executescript(DDL)

    # Insert sections (level 1)
    section_ids = {}
    for i, (code, title, title_en, btype) in enumerate(sections, 1):
        c = db.execute(
            """INSERT INTO chapter (parent_id, sort_order, level, title, subtitle, code, bracket_type)
               VALUES (NULL, ?, 1, ?, ?, ?, ?)""",
            (i, f"{code} {title}" if title else code, title_en, code, btype),
        )
        section_ids[code] = c.lastrowid

    # Insert sub-sections (level 2)
    sub_ids = {}
    for i, (code, title, title_en, btype) in enumerate(subsections, 1):
        parent_code = code.split(".")[0]
        parent_id = section_ids.get(parent_code)
        c = db.execute(
            """INSERT INTO chapter (parent_id, sort_order, level, title, subtitle, code, bracket_type)
               VALUES (?, ?, 2, ?, ?, ?, ?)""",
            (parent_id, i, f"{code} {title}" if title else code, title_en, code, btype),
        )
        sub_ids[code] = c.lastrowid

    # Insert groups (level 3)
    group_ids = {}
    sort_idx = 1
    all_group_codes = sorted(groups.keys())
    for code in all_group_codes:
        title, title_en, btype = groups[code]
        parts = code.split(".")
        parent_code = ".".join(parts[:2])
        parent_id = sub_ids.get(parent_code)
        is_implicit = 1 if code in implicit_codes else 0
        c = db.execute(
            """INSERT INTO chapter (parent_id, sort_order, level, title, subtitle, code, bracket_type, is_implicit)
               VALUES (?, ?, 3, ?, ?, ?, ?, ?)""",
            (parent_id, sort_idx, f"{code} {title}" if title else code, title_en, code, btype, is_implicit),
        )
        group_ids[code] = c.lastrowid
        sort_idx += 1

    # Insert items (level 4)
    item_row_ids = {}  # code -> boq_item rowid
    for item in items:
        parts = item["code"].split(".")
        parent_code = ".".join(parts[:3])
        chapter_id = group_ids.get(parent_code)
        try:
            item_sort = int(parts[3])
        except (ValueError, IndexError):
            item_sort = 0
        c = db.execute(
            """INSERT INTO boq_item (chapter_id, code, name, name_en, unit, description, type,
               work_content, calc_rule, sort_order, amount, quantity, rate, labour, materials, mech)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chapter_id, item["code"], item["name"], item["name_en"], item["unit"],
                item["description"], item["type"], item["work_content"], item["calc_rule"],
                item_sort, item["amount"], item["quantity"], item["rate"],
                item["labour"], item["materials"], item["mech"],
            ),
        )
        item_row_ids[item["code"]] = c.lastrowid

    # Insert resource definitions
    res_def_ids = {}  # (sub_code, col_letter) -> id
    for sub_code, resources in resource_defs.items():
        chapter_id = sub_ids.get(sub_code)
        if chapter_id is None:
            continue
        for i, res in enumerate(resources):
            c = db.execute(
                """INSERT INTO boq_resource_def (chapter_id, col_letter, sort_order,
                   resource_name, resource_unit, unit_price)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chapter_id, res["col"], i, res["name"], res["unit"], res["unit_price"]),
            )
            res_def_ids[(sub_code, res["col"])] = c.lastrowid

    # Insert resource quantities
    for item in items:
        if not item.get("consumption"):
            continue
        item_id = item_row_ids.get(item["code"])
        if item_id is None:
            continue
        parts = item["code"].split(".")
        sub_code = ".".join(parts[:2])
        for col_letter, qty in item["consumption"].items():
            rd_id = res_def_ids.get((sub_code, col_letter))
            if rd_id is None:
                continue
            db.execute(
                """INSERT INTO boq_resource_qty (item_id, resource_def_id, consumption)
                   VALUES (?, ?, ?)""",
                (item_id, rd_id, qty),
            )

    # Create compatibility layer for Norms-AI browser
    db.executescript(COMPAT_DDL)
    write_compatibility_layer(db, sections, subsections, groups, items, resource_defs)

    db.commit()
    db.close()


# ── Verification ─────────────────────────────────────────────

def verify(db_path, expected_sections, expected_subs, expected_groups,
           expected_items, expected_implicit):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row

    l1 = db.execute("SELECT COUNT(*) FROM chapter WHERE level=1").fetchone()[0]
    l2 = db.execute("SELECT COUNT(*) FROM chapter WHERE level=2").fetchone()[0]
    l3 = db.execute("SELECT COUNT(*) FROM chapter WHERE level=3").fetchone()[0]
    item_count = db.execute("SELECT COUNT(*) FROM boq_item").fetchone()[0]
    imp = db.execute("SELECT COUNT(*) FROM chapter WHERE is_implicit=1").fetchone()[0]
    orphan = db.execute(
        "SELECT COUNT(*) FROM boq_item WHERE chapter_id NOT IN (SELECT id FROM chapter)"
    ).fetchone()[0]

    res_defs = db.execute("SELECT COUNT(*) FROM boq_resource_def").fetchone()[0]
    res_qtys = db.execute("SELECT COUNT(*) FROM boq_resource_qty").fetchone()[0]
    norms = db.execute("SELECT COUNT(*) FROM norms_item").fetchone()[0]

    items_with_rate = db.execute(
        "SELECT COUNT(*) FROM boq_item WHERE rate IS NOT NULL"
    ).fetchone()[0]
    items_with_amount = db.execute(
        "SELECT COUNT(*) FROM boq_item WHERE amount IS NOT NULL"
    ).fetchone()[0]
    items_with_qty = db.execute(
        "SELECT COUNT(*) FROM boq_item WHERE quantity IS NOT NULL"
    ).fetchone()[0]

    print(f"\n{'='*50}")
    print("Verification Report")
    print(f"{'='*50}")
    print(f"  L1 Sections:        {l1:>4}  (expected {expected_sections}) {'OK' if l1 == expected_sections else 'MISMATCH'}")
    print(f"  L2 Sub-sections:    {l2:>4}  (expected {expected_subs}) {'OK' if l2 == expected_subs else 'MISMATCH'}")
    print(f"  L3 Groups:          {l3:>4}  (expected {expected_groups}) {'OK' if l3 == expected_groups else 'MISMATCH'}")
    print(f"  BOQ Items:          {item_count:>4}  (expected {expected_items}) {'OK' if item_count == expected_items else 'MISMATCH'}")
    print(f"  Implicit groups:    {imp:>4}  (expected {expected_implicit}) {'OK' if imp == expected_implicit else 'MISMATCH'}")
    print(f"  Orphan items:       {orphan:>4}  {'OK' if orphan == 0 else 'HAS ORPHANS!'}")
    print(f"  ---")
    print(f"  Resource defs:      {res_defs:>4}")
    print(f"  Resource quantities:{res_qtys:>4}")
    print(f"  Norms items (compat):{norms:>4}")
    print(f"  Items with rate:    {items_with_rate:>4}")
    print(f"  Items with amount:  {items_with_amount:>4}")
    print(f"  Items with quantity:{items_with_qty:>4}")

    sample_items = db.execute(
        "SELECT code, name, unit, rate, labour, materials, mech FROM boq_item WHERE rate IS NOT NULL LIMIT 5"
    ).fetchall()
    print(f"\n  Sample items with cost data:")
    for s in sample_items:
        print(f"    {s[0]}  {s[1]}  [{s[2]}]  rate={s[3]} labour={s[4]} mat={s[5]} mech={s[6]}")

    sample_res = db.execute(
        """SELECT rd.resource_name, rd.resource_unit, rd.unit_price, COUNT(rq.id) as cnt, SUM(rq.consumption) as total
           FROM boq_resource_def rd
           LEFT JOIN boq_resource_qty rq ON rq.resource_def_id = rd.id
           GROUP BY rd.id
           LIMIT 10"""
    ).fetchall()
    print(f"\n  Sample resource defs (with usage):")
    for s in sample_res:
        print(f"    {s[0]} [{s[1]}] price={s[2]} used_by={s[3]} items total_qty={s[4]}")

    db.close()

    all_ok = (l1 == expected_sections and l2 == expected_subs and l3 == expected_groups
              and item_count == expected_items and orphan == 0)
    return all_ok


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import BOQ Excel to SQLite (v2 with consumption data)")
    parser.add_argument("xlsx", help="Path to the BOQ Excel file")
    parser.add_argument("--db", help="Output SQLite path (default: auto-generated)")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"Error: file not found: {xlsx_path}")
        sys.exit(1)

    if args.db:
        db_path = args.db
    else:
        stem = xlsx_path.stem
        db_path = str(Path(__file__).resolve().parent.parent / "db" / f"{stem}.sqlite")

    print(f"Source: {xlsx_path}")
    print(f"Target: {db_path}")

    # Phase 1: Parse
    print("\n[1/4] Parsing XML (shared strings + sheet data)...")
    rows, resource_defs = parse_sheet(str(xlsx_path))
    print(f"  Parsed {len(rows)} data rows (with A-column codes)")
    print(f"  Resource definitions: {len(resource_defs)} subsections")
    for sub_code, res_list in resource_defs.items():
        names = [r["name"] for r in res_list]
        print(f"    {sub_code}: {len(res_list)} resources — {', '.join(names[:5])}{'...' if len(names) > 5 else ''}")

    # Phase 2: Build hierarchy
    print("\n[2/4] Building hierarchy...")
    sections, subsections, groups, items, implicit = build_hierarchy(rows)
    print(f"  L1 Sections:     {len(sections)}")
    print(f"  L2 Sub-sections: {len(subsections)}")
    print(f"  L3 Groups:       {len(groups)} ({len(implicit)} implicit)")
    print(f"  L4 Items:        {len(items)}")

    # Phase 3: Write DB
    print("\n[3/4] Writing SQLite...")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    write_db(db_path, sections, subsections, groups, items, implicit, resource_defs)
    print(f"  Written to {db_path}")

    # Phase 4: Verify
    print("\n[4/4] Verifying...")
    ok = verify(db_path, len(sections), len(subsections), len(groups),
                len(items), len(implicit))

    if ok:
        print(f"\nDone. Database: {db_path}")
    else:
        print("\nVerification FAILED — check the report above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
