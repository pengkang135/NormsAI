"""骨架自检：9 项硬性判据，全绿即视为骨架建成。

exit 0 = 通过；exit 1 = 有失败项。

用法：
    python -m scripts.enterprise.verify_skeleton
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import DB_OUT, BROWSER_JSON, DISCIPLINES


def run_check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        return name, False, f"exception: {e}"
    return name, ok, detail


def main():
    if not DB_OUT.exists():
        print(f"! DB not found: {DB_OUT}")
        sys.exit(1)

    conn = sqlite3.connect(DB_OUT)

    def c1_db_size():
        mb = DB_OUT.stat().st_size / 1024 / 1024
        return (15 <= mb <= 100, f"{mb:.1f} MB")

    def c2_wbs_class():
        n = conn.execute("SELECT COUNT(*) FROM wbs_class").fetchone()[0]
        hint = conn.execute("SELECT COUNT(*) FROM wbs_class WHERE beijing_hint IS NOT NULL").fetchone()[0]
        return (n == 444 and hint == 338, f"total={n}, hint={hint}")

    def c3_source_registry():
        n = conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0]
        return (n == 3, f"rows={n}")

    def c4_bj2012_main_counts():
        expected = {"chapter": 4377, "Norm": 25330, "Consumption": 29361, "Content": 290823}
        actual = {
            "chapter":     conn.execute("SELECT COUNT(*) FROM src_bj2012_chapter WHERE source_id=1").fetchone()[0],
            "Norm":        conn.execute("SELECT COUNT(*) FROM src_bj2012_norm WHERE source_id=1").fetchone()[0],
            "Consumption": conn.execute("SELECT COUNT(*) FROM src_bj2012_consumption WHERE source_id=1").fetchone()[0],
            "Content":     conn.execute("SELECT COUNT(*) FROM src_bj2012_content WHERE source_id=1").fetchone()[0],
        }
        return (actual == expected, str(actual))

    def c4b_bj2012_repair_counts():
        expected = {"chapter": 1638, "Norm": 13552, "Consumption": 4320, "Content": 113893}
        actual = {
            "chapter":     conn.execute("SELECT COUNT(*) FROM src_bj2012_chapter WHERE source_id=2").fetchone()[0],
            "Norm":        conn.execute("SELECT COUNT(*) FROM src_bj2012_norm WHERE source_id=2").fetchone()[0],
            "Consumption": conn.execute("SELECT COUNT(*) FROM src_bj2012_consumption WHERE source_id=2").fetchone()[0],
            "Content":     conn.execute("SELECT COUNT(*) FROM src_bj2012_content WHERE source_id=2").fetchone()[0],
        }
        return (actual == expected, str(actual))

    def c4c_jts_counts():
        expected = {"chapter": 23, "norms_table": 257, "norms_item": 34024}
        actual = {
            "chapter":     conn.execute("SELECT COUNT(*) FROM src_jts276_chapter WHERE source_id=3").fetchone()[0],
            "norms_table": conn.execute("SELECT COUNT(*) FROM src_jts276_norms_table WHERE source_id=3").fetchone()[0],
            "norms_item":  conn.execute("SELECT COUNT(*) FROM src_jts276_norms_item WHERE source_id=3").fetchone()[0],
        }
        return (actual == expected, str(actual))

    def c5_utf8_sanity():
        row = conn.execute(
            "SELECT chap_Name FROM src_bj2012_chapter WHERE source_id=1 AND chap_ID=100000000"
        ).fetchone()
        got = row[0] if row else ""
        return (got == "房屋建筑与装饰工程", f"chap_ID=100000000 → {got!r}")

    def c6_discipline_null_chapter():
        n = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_chapter WHERE discipline IS NULL"
        ).fetchone()[0]
        return (n == 0, f"NULL discipline rows in chapter: {n}")

    def c7_orphan_chapter():
        # 主库要 = 0；修缮库源数据本身有 1 个孤儿 → 允许 <= 1
        n1 = conn.execute("""SELECT COUNT(*) FROM src_bj2012_chapter
                             WHERE source_id=1 AND chap_PID!=0
                               AND chap_PID NOT IN (SELECT chap_ID FROM src_bj2012_chapter WHERE source_id=1)""").fetchone()[0]
        n2 = conn.execute("""SELECT COUNT(*) FROM src_bj2012_chapter
                             WHERE source_id=2 AND chap_PID!=0
                               AND chap_PID NOT IN (SELECT chap_ID FROM src_bj2012_chapter WHERE source_id=2)""").fetchone()[0]
        return (n1 == 0 and n2 <= 1, f"main={n1}, repair={n2} (repair 源库自身脏数据允许 ≤ 1)")

    def c8_mapping_empty():
        n = conn.execute("SELECT COUNT(*) FROM wbs_norm_mapping").fetchone()[0]
        return (n == 0, f"wbs_norm_mapping rows: {n}")

    def c9_views_queryable():
        results = {}
        for d in DISCIPLINES:
            results[d] = conn.execute(f'SELECT COUNT(*) FROM "vw_disc_{d}"').fetchone()[0]
        # 房建 & 装修 必须 > 0；其他 4 专业允许 = 0
        ok = results["房建"] > 0 and results["装修"] > 0
        return (ok, str(results))

    def c10_browser_json():
        exists = BROWSER_JSON.exists()
        size_kb = BROWSER_JSON.stat().st_size / 1024 if exists else 0
        return (exists and size_kb > 100, f"exists={exists}, size={size_kb:.0f} KB")

    checks = [
        ("[1] DB 文件大小",              c1_db_size),
        ("[2] wbs_class 444 行 & 338 hint", c2_wbs_class),
        ("[3] source_registry 3 行",      c3_source_registry),
        ("[4a] 主库 4 表行数",             c4_bj2012_main_counts),
        ("[4b] 修缮库 4 表行数",           c4b_bj2012_repair_counts),
        ("[4c] JTS 3 表行数",             c4c_jts_counts),
        ("[5] UTF-8 中文抽检",            c5_utf8_sanity),
        ("[6] chapter.discipline 无 NULL", c6_discipline_null_chapter),
        ("[7] chap_PID 孤儿",             c7_orphan_chapter),
        ("[8] wbs_norm_mapping 为空",     c8_mapping_empty),
        ("[9] 6 视图可查 + 房建/装修>0",   c9_views_queryable),
        ("[10] 前端 JSON 存在",            c10_browser_json),
    ]

    print("=" * 60)
    print("骨架自检报告")
    print("=" * 60)
    failed = 0
    for name, fn in checks:
        n, ok, detail = run_check(name, fn)
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {n:<32} {detail}")
        if not ok:
            failed += 1
    print("=" * 60)
    print(f"通过: {len(checks) - failed} / {len(checks)}")
    conn.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
