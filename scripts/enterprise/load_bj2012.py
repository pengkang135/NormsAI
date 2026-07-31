"""北京 2012 主库 & 修缮库 → src_bj2012_*（ATTACH + INSERT SELECT，秒级）。

用法:
    python -m scripts.enterprise.load_bj2012          # 只导主库(source_id=1)
    python -m scripts.enterprise.load_bj2012 --repair # 只导修缮(source_id=2)
    python -m scripts.enterprise.load_bj2012 --both
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import DB_OUT, DB_SRC, SOURCES


# 字段清单必须与 init_ent_schema 里的一致（不含 discipline / source_id）
CHAPTER_COLS = ["chap_ID", "chap_PID", "chap_Name", "chap_Content", "chap_code", "chap_Index"]

NORM_COLS = [
    "norm_ID", "chap_ID", "chap_Code", "norm_SortID", "norm_Specialty",
    "norm_Code", "norm_Name", "norm_Units", "norm_BaseUnits", "norm_UnitsQuotiety",
    "norm_ManPrice", "norm_MaterialPrice", "norm_MachinePrice", "norm_OtherPrice",
    "norm_MainMaterialPrice", "norm_EquipmentPrice",
    "norm_AttachTag1", "norm_AttachTag", "norm_isEntity", "norm_Tag",
    "norm_direct", "norm_Alias", "Norm_Content",
]

CONS_COLS = [
    "cons_ID", "kind_ID", "kind_Code", "cons_Code", "cons_Alias", "cons_Name",
    "cons_Standard", "cons_Units", "cons_Price", "cons_Market", "cons_Supply",
    "cons_ThreeTag", "cons_ThreeQuotiety", "cons_Style", "cons_UnitQuotiety",
    "cons_CompositeStyle", "cons_IsCalculate", "cons_CalculateBasic",
]

CONTENT_COLS = [
    "cont_ID", "norm_ID", "cons_ID", "cont_Amount", "cont_Type",
    "cont_IsMainMaterial", "cont_IsCalculatePrice",
]


def _quote(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


def _load_one(conn: sqlite3.Connection, src_file: Path, source_id: int) -> dict:
    """从 src ATTACH 到主 conn，然后 INSERT SELECT 4 张表。"""
    print(f"  [{source_id}] attaching {src_file.name}...")
    conn.execute(f'ATTACH DATABASE "{src_file}" AS src')
    try:
        # 先清空该 source_id 的历史数据（幂等重跑）
        for t in ["src_bj2012_content", "src_bj2012_consumption",
                  "src_bj2012_norm", "src_bj2012_chapter"]:
            conn.execute(f'DELETE FROM {t} WHERE source_id = ?', (source_id,))

        stats = {}

        # chapter
        cols = _quote(CHAPTER_COLS)
        conn.execute(f"""
            INSERT INTO src_bj2012_chapter (source_id, {cols})
            SELECT {source_id}, {cols} FROM src.chapter
        """)
        stats["chapter"] = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_chapter WHERE source_id=?",
            (source_id,)
        ).fetchone()[0]

        # Norm
        cols = _quote(NORM_COLS)
        conn.execute(f"""
            INSERT INTO src_bj2012_norm (source_id, {cols})
            SELECT {source_id}, {cols} FROM src."Norm"
        """)
        stats["Norm"] = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_norm WHERE source_id=?",
            (source_id,)
        ).fetchone()[0]

        # Consumption
        cols = _quote(CONS_COLS)
        conn.execute(f"""
            INSERT INTO src_bj2012_consumption (source_id, {cols})
            SELECT {source_id}, {cols} FROM src."Consumption"
        """)
        stats["Consumption"] = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_consumption WHERE source_id=?",
            (source_id,)
        ).fetchone()[0]

        # Content
        cols = _quote(CONTENT_COLS)
        conn.execute(f"""
            INSERT INTO src_bj2012_content (source_id, {cols})
            SELECT {source_id}, {cols} FROM src."Content"
        """)
        stats["Content"] = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_content WHERE source_id=?",
            (source_id,)
        ).fetchone()[0]

        conn.commit()

        # 更新 source_registry 统计
        conn.execute(
            "UPDATE source_registry SET row_stats_json = ? WHERE source_id = ?",
            (json.dumps(stats, ensure_ascii=False), source_id),
        )
        conn.commit()

        # 孤儿检查
        orphan = conn.execute(f"""
            SELECT COUNT(*) FROM src_bj2012_chapter
            WHERE source_id = ? AND chap_PID != 0
              AND chap_PID NOT IN (SELECT chap_ID FROM src_bj2012_chapter WHERE source_id = ?)
        """, (source_id, source_id)).fetchone()[0]
        stats["orphan_chapter"] = orphan

        # 中文抽检
        row = conn.execute(
            "SELECT chap_Name FROM src_bj2012_chapter WHERE source_id=? AND chap_PID=0 LIMIT 1",
            (source_id,)
        ).fetchone()
        stats["sample_chinese"] = row[0] if row else None

        return stats
    finally:
        conn.execute("DETACH DATABASE src")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repair", action="store_true", help="导入修缮库 (source_id=2)")
    ap.add_argument("--both",   action="store_true", help="两个都导")
    args = ap.parse_args()

    if not args.repair and not args.both:
        targets = ["BJ2012_MAIN"]
    elif args.both:
        targets = ["BJ2012_MAIN", "BJ2012_REPAIR"]
    else:
        targets = ["BJ2012_REPAIR"]

    conn = sqlite3.connect(DB_OUT)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for key in targets:
            s = SOURCES[key]
            src_file = DB_SRC / s["db_file"]
            if not src_file.exists():
                print(f"  ! missing: {src_file}")
                continue
            stats = _load_one(conn, src_file, s["source_id"])
            print(f"[ok] {key} (source_id={s['source_id']}):")
            for k, v in stats.items():
                print(f"     {k}: {v}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
