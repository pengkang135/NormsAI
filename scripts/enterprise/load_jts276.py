"""JTS 港口水工 → src_jts276_*（ATTACH + INSERT SELECT）。

用法:
    python -m scripts.enterprise.load_jts276
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import DB_OUT, DB_SRC, SOURCES

CHAPTER_COLS = [
    "id", "parent_id", "sort_order", "level", "title", "subtitle",
    "toc_page", "start_page", "end_page", "is_appendix",
]

NORMS_TABLE_COLS = [
    "id", "chapter_id", "section_title", "subsection_title", "work_content",
    "unit", "page", "seq_on_page", "header_json", "row_count", "col_count",
]

NORMS_ITEM_COLS = [
    "id", "table_id", "page", "norms_code", "sort_order",
    "attr_level1", "attr_level2", "attr_level3", "attr_level4",
    "attr1_label", "attr2_label", "attr3_label", "attr4_label",
    "cost_item", "cost_item_unit", "amount", "ocr_source", "data_quality",
]


def _quote(cols): return ", ".join(f'"{c}"' for c in cols)


def main():
    s = SOURCES["JTS276_1"]
    source_id = s["source_id"]
    src_file = DB_SRC / s["db_file"]
    if not src_file.exists():
        print(f"  ! missing: {src_file}")
        return
    conn = sqlite3.connect(DB_OUT)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(f'ATTACH DATABASE "{src_file}" AS src')
        try:
            for t in ["src_jts276_norms_item", "src_jts276_norms_table", "src_jts276_chapter"]:
                conn.execute(f"DELETE FROM {t} WHERE source_id = ?", (source_id,))

            stats = {}
            for tgt, cols, src_tbl in [
                ("src_jts276_chapter",     CHAPTER_COLS,     "chapter"),
                ("src_jts276_norms_table", NORMS_TABLE_COLS, "norms_table"),
                ("src_jts276_norms_item",  NORMS_ITEM_COLS,  "norms_item"),
            ]:
                cols_q = _quote(cols)
                conn.execute(f"""
                    INSERT INTO {tgt} (source_id, {cols_q})
                    SELECT {source_id}, {cols_q} FROM src."{src_tbl}"
                """)
                stats[src_tbl] = conn.execute(
                    f"SELECT COUNT(*) FROM {tgt} WHERE source_id=?", (source_id,)
                ).fetchone()[0]

            conn.execute(
                "UPDATE source_registry SET row_stats_json = ? WHERE source_id = ?",
                (json.dumps(stats, ensure_ascii=False), source_id),
            )
            conn.commit()
            print(f"[ok] JTS276_1 (source_id={source_id}):")
            for k, v in stats.items():
                print(f"     {k}: {v}")
        finally:
            conn.execute("DETACH DATABASE src")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
