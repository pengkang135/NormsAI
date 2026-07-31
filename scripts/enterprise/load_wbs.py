"""朱海 Excel → wbs_class（幂等 UPSERT）。

用法:
    python -m scripts.enterprise.load_wbs
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import openpyxl

from scripts.enterprise.config_ent import (
    DB_OUT, WBS_XLSX, WBS_AA_DISCIPLINE, WBS_COL,
)


def _derive_level(aa: str, bb: str, cc: str, ddd: str, eee: str) -> int:
    """按 EEE=000 / DDD=000 / CC=00 / BB=00 逐级判断层级。"""
    if eee != "000":
        return 5
    if ddd != "000":
        return 4
    if cc != "00":
        return 3
    if bb != "00":
        return 2
    return 1


def _derive_parent(code: str, level: int) -> str | None:
    """按当前层级把右侧段位归零得到 parent_code。level=1 → None。"""
    if level == 5:
        return code[:9] + "000"
    if level == 4:
        return code[:6] + "000000"
    if level == 3:
        return code[:4] + "00000000"
    if level == 2:
        return code[:2] + "0000000000"
    return None


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def load_wbs(xlsx: Path, db_path: Path) -> dict:
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb.worksheets[0]  # 主表

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")  # 允许先插子节点后插父节点
        rows_inserted = 0
        rows_skipped = 0
        level_hist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        hint_count = 0

        # 先收集所有行，按 level 排序（level 小的先插，满足 FK）
        buffer = []
        for row_idx, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            code_v = r[WBS_COL["wbs_code"]]
            if code_v is None:
                continue
            code = str(code_v).strip()
            if len(code) != 12 or not code.isdigit():
                rows_skipped += 1
                continue

            aa  = code[0:2]
            bb  = code[2:4]
            cc  = code[4:6]
            ddd = code[6:9]
            eee = code[9:12]
            level = _derive_level(aa, bb, cc, ddd, eee)
            parent = _derive_parent(code, level)
            discipline = WBS_AA_DISCIPLINE.get(aa)
            beijing_hint = _clean(r[WBS_COL["beijing_hint"]])
            if beijing_hint:
                hint_count += 1

            buffer.append({
                "wbs_code":     code,
                "parent_code":  parent,
                "level":        level,
                "aa": aa, "bb": bb, "cc": cc, "ddd": ddd, "eee": eee,
                "name_cn":      _clean(r[WBS_COL["name_cn"]]) or "(未命名)",
                "name_en":      _clean(r[WBS_COL["name_en"]]),
                "work_content": _clean(r[WBS_COL["work_content"]]),
                "standard_unit": _clean(r[WBS_COL["unit"]]),
                "calc_rule":    _clean(r[WBS_COL["calc_rule"]]),
                "beijing_hint": beijing_hint,
                "discipline":   discipline,
                "source_row":   row_idx,
            })

        buffer.sort(key=lambda x: x["level"])
        for row in buffer:
            conn.execute(
                """INSERT OR REPLACE INTO wbs_class
                   (wbs_code, parent_code, level, aa, bb, cc, ddd, eee,
                    name_cn, name_en, work_content, standard_unit, calc_rule,
                    beijing_hint, discipline, extension_flag, source_row)
                   VALUES (:wbs_code, :parent_code, :level, :aa, :bb, :cc, :ddd, :eee,
                    :name_cn, :name_en, :work_content, :standard_unit, :calc_rule,
                    :beijing_hint, :discipline, 0, :source_row)""",
                row,
            )
            rows_inserted += 1
            level_hist[row["level"]] += 1

        conn.commit()

        # 验证：AA 分布、孤儿检查
        aa_dist = dict(conn.execute(
            "SELECT aa, COUNT(*) FROM wbs_class GROUP BY aa"
        ).fetchall())
        orphan_count = conn.execute(
            """SELECT COUNT(*) FROM wbs_class
               WHERE parent_code IS NOT NULL
                 AND parent_code NOT IN (SELECT wbs_code FROM wbs_class)"""
        ).fetchone()[0]

        return {
            "rows_inserted": rows_inserted,
            "rows_skipped":  rows_skipped,
            "level_dist":    level_hist,
            "aa_dist":       aa_dist,
            "beijing_hint_nonempty": hint_count,
            "orphan_count":  orphan_count,
        }
    finally:
        conn.close()


def main():
    stats = load_wbs(WBS_XLSX, DB_OUT)
    print(f"[ok] load_wbs -> {DB_OUT}")
    for k, v in stats.items():
        print(f"     {k}: {v}")


if __name__ == "__main__":
    main()
