"""从 ent_norms.sqlite 导出前端 JSON。

产物：
  - ent_norms_data.json  骨架 + 统计 (小，首屏)
  - ent_pool_data.json    源库定额池全量 (大，切到源库视角时加载)

用法:
    python -m scripts.enterprise.export_browser_json
"""
from __future__ import annotations
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import DB_OUT, BROWSER_JSON, OUTPUT_DIR, DISCIPLINES

POOL_JSON = OUTPUT_DIR / "ent_pool_data.json"


def _row_dict(cursor, row):
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


def _rows(conn, sql, params=()):
    cur = conn.execute(sql, params)
    return [_row_dict(cur, r) for r in cur.fetchall()]


def _build_wbs_tree_by_disc(conn):
    rows = _rows(conn, """
        SELECT wbs_code, parent_code, level, name_cn, name_en,
               work_content, standard_unit, calc_rule, beijing_hint, discipline
        FROM wbs_class ORDER BY wbs_code
    """)
    by_code = {}
    for r in rows:
        r["children"] = []
        by_code[r["wbs_code"]] = r
    roots_by_disc = defaultdict(list)
    for r in rows:
        pc = r["parent_code"]
        if pc and pc in by_code:
            by_code[pc]["children"].append(r)
        else:
            roots_by_disc[r["discipline"]].append(r)
    return dict(roots_by_disc)


def _stats(conn):
    return {
        "wbs_class_total": conn.execute("SELECT COUNT(*) FROM wbs_class").fetchone()[0],
        "wbs_class_by_disc": dict(conn.execute(
            "SELECT discipline, COUNT(*) FROM wbs_class GROUP BY discipline").fetchall()),
        "wbs_beijing_hint_count": conn.execute(
            "SELECT COUNT(*) FROM wbs_class WHERE beijing_hint IS NOT NULL").fetchone()[0],
        "bj2012_main": {
            "chapter": conn.execute("SELECT COUNT(*) FROM src_bj2012_chapter WHERE source_id=1").fetchone()[0],
            "norm":    conn.execute("SELECT COUNT(*) FROM src_bj2012_norm WHERE source_id=1").fetchone()[0],
        },
        "bj2012_repair": {
            "chapter": conn.execute("SELECT COUNT(*) FROM src_bj2012_chapter WHERE source_id=2").fetchone()[0],
            "norm":    conn.execute("SELECT COUNT(*) FROM src_bj2012_norm WHERE source_id=2").fetchone()[0],
        },
        "jts276": {
            "chapter":    conn.execute("SELECT COUNT(*) FROM src_jts276_chapter WHERE source_id=3").fetchone()[0],
            "norms_item": conn.execute("SELECT COUNT(*) FROM src_jts276_norms_item WHERE source_id=3").fetchone()[0],
        },
        "mapping_total": conn.execute("SELECT COUNT(*) FROM wbs_norm_mapping").fetchone()[0],
    }


def export_skeleton(conn):
    """轻量骨架 JSON (首屏)。"""
    payload = {
        "sources":     _rows(conn, "SELECT * FROM source_registry ORDER BY source_id"),
        "disciplines": DISCIPLINES,
        "stats":       _stats(conn),
        "wbs_tree_by_disc": _build_wbs_tree_by_disc(conn),
    }
    BROWSER_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8")
    return BROWSER_JSON.stat().st_size


def export_pool(conn):
    """完整源库定额池（大 JSON，切到 Pool 视图时加载）。

    结构：
      bj_chapters:  [ {source_id, chap_ID, chap_PID, chap_code, chap_Name, discipline}, ... ]
      bj_norms:     [ {source_id, norm_ID, chap_ID, norm_Code, norm_Name, unit,
                       man, mat, mach, other, main_mat, equip, discipline}, ... ]
      jts_chapters: [ {source_id, id, parent_id, level, title, subtitle}, ... ]
      jts_items:    [ {source_id, id, table_id, norms_code, attr1..4, cost_item, unit, amount}, ... ]
    """
    payload = {
        "bj_chapters": _rows(conn, """
            SELECT source_id, chap_ID, chap_PID, chap_code, chap_Name, discipline
            FROM src_bj2012_chapter
            ORDER BY source_id, chap_ID
        """),
        "bj_norms": _rows(conn, """
            SELECT source_id, norm_ID, chap_ID, norm_Code, norm_Name,
                   norm_Units AS unit,
                   norm_ManPrice AS man,
                   norm_MaterialPrice AS mat,
                   norm_MachinePrice AS mach,
                   norm_OtherPrice AS other,
                   norm_MainMaterialPrice AS main_mat,
                   norm_EquipmentPrice AS equip,
                   discipline
            FROM src_bj2012_norm
            ORDER BY source_id, chap_ID, norm_ID
        """),
        "jts_chapters": _rows(conn, """
            SELECT source_id, id, parent_id, level, title, subtitle, sort_order
            FROM src_jts276_chapter
            ORDER BY source_id, sort_order, id
        """),
        "jts_norms_tables": _rows(conn, """
            SELECT source_id, id, chapter_id, section_title, subsection_title, unit
            FROM src_jts276_norms_table
            ORDER BY source_id, id
        """),
        "jts_items": _rows(conn, """
            SELECT source_id, id, table_id, norms_code,
                   attr_level1 AS a1, attr_level2 AS a2,
                   cost_item, cost_item_unit AS unit, amount
            FROM src_jts276_norms_item
            ORDER BY source_id, id
        """),
    }
    POOL_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8")
    return POOL_JSON.stat().st_size


def main():
    conn = sqlite3.connect(DB_OUT)
    try:
        n1 = export_skeleton(conn)
        n2 = export_pool(conn)
        print(f"[ok] {BROWSER_JSON.name}  {n1/1024:.0f} KB")
        print(f"[ok] {POOL_JSON.name}  {n2/1024/1024:.2f} MB")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
