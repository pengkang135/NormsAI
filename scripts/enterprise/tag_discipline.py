"""给 src_bj2012_chapter / src_bj2012_norm 打 discipline 标签。

三阶段：
  1) 粗分：按 chap_code 前 2 位 → discipline（主库用 MAIN 映射，修缮用 REPAIR 映射）
  2) 主库 01 分部装饰二次拆分：chap_Name 命中关键词 → '装修'，子孙递归继承
  3) JTS 全部标 '水工'
  4) Norm 表 join chapter 反填 discipline

用法:
    python -m scripts.enterprise.tag_discipline
"""
from __future__ import annotations
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import (
    DB_OUT, BJ2012_DISCIPLINE_MAP, BJ2012R_DISCIPLINE_MAP,
    BJ2012_DECOR_KEYWORDS, JTS_DISCIPLINE,
)


def _tag_by_prefix(conn: sqlite3.Connection, source_id: int, prefix_map: dict):
    """按 chap_code 前 2 位查 prefix_map 打 discipline。"""
    conn.execute(
        "UPDATE src_bj2012_chapter SET discipline = NULL WHERE source_id = ?",
        (source_id,),
    )
    for prefix, disc in prefix_map.items():
        conn.execute(
            """UPDATE src_bj2012_chapter
                  SET discipline = ?
                WHERE source_id = ? AND substr(chap_code, 1, 2) = ?""",
            (disc, source_id, prefix),
        )


def _split_decor_subtree(conn: sqlite3.Connection, source_id: int):
    """
    主库 01 分部装饰二次拆分：
      1) 种子节点：chap_code 恰为 '01.NN'（二级章节，长度=5）且 chap_Name 命中关键词
      2) 递归收集其所有后代
      3) UPDATE discipline='装修'
    只在二级章节找种子，避免命中一级顶层（'01 房屋建筑与装饰工程' 名字里带"装饰"）。
    """
    kw_conds = " OR ".join(["chap_Name LIKE ?"] * len(BJ2012_DECOR_KEYWORDS))
    kw_params = [f"%{kw}%" for kw in BJ2012_DECOR_KEYWORDS]

    seeds = conn.execute(
        f"""SELECT chap_ID FROM src_bj2012_chapter
             WHERE source_id = ?
               AND chap_code LIKE '01.__'
               AND length(chap_code) = 5
               AND ({kw_conds})""",
        [source_id] + kw_params,
    ).fetchall()
    seed_ids = {r[0] for r in seeds}

    # 递归收集后代
    all_ids = set(seed_ids)
    frontier = set(seed_ids)
    while frontier:
        placeholders = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"""SELECT chap_ID FROM src_bj2012_chapter
                 WHERE source_id = ? AND chap_PID IN ({placeholders})""",
            [source_id, *frontier],
        ).fetchall()
        next_frontier = {r[0] for r in rows} - all_ids
        all_ids |= next_frontier
        frontier = next_frontier

    if all_ids:
        placeholders = ",".join("?" * len(all_ids))
        conn.execute(
            f"""UPDATE src_bj2012_chapter
                   SET discipline = '装修'
                 WHERE source_id = ? AND chap_ID IN ({placeholders})""",
            [source_id, *all_ids],
        )
    return len(all_ids)


def _tag_norm_from_chapter(conn: sqlite3.Connection, source_id: int):
    """Norm 表 discipline 从 chapter 反填。"""
    conn.execute(
        """UPDATE src_bj2012_norm
              SET discipline = (
                SELECT discipline FROM src_bj2012_chapter c
                 WHERE c.source_id = src_bj2012_norm.source_id
                   AND c.chap_ID   = src_bj2012_norm.chap_ID
              )
            WHERE source_id = ?""",
        (source_id,),
    )


def main():
    conn = sqlite3.connect(DB_OUT)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        # ---- 主库 (source_id=1) ----
        _tag_by_prefix(conn, source_id=1, prefix_map=BJ2012_DISCIPLINE_MAP)
        decor_count = _split_decor_subtree(conn, source_id=1)
        _tag_norm_from_chapter(conn, source_id=1)
        conn.commit()

        # ---- 修缮库 (source_id=2) ----
        _tag_by_prefix(conn, source_id=2, prefix_map=BJ2012R_DISCIPLINE_MAP)
        _tag_norm_from_chapter(conn, source_id=2)
        conn.commit()

        # 打印统计
        print("=== src_bj2012_chapter discipline 分布 ===")
        for source_id, name in [(1, "主库"), (2, "修缮")]:
            print(f"  [{name}] source_id={source_id}")
            for r in conn.execute(
                """SELECT discipline, COUNT(*) FROM src_bj2012_chapter
                    WHERE source_id = ? GROUP BY discipline
                    ORDER BY COUNT(*) DESC""", (source_id,)
            ).fetchall():
                print(f"     {r[0] or '(NULL)':<10} : {r[1]}")

        print("\n=== src_bj2012_norm discipline 分布 ===")
        for source_id, name in [(1, "主库"), (2, "修缮")]:
            print(f"  [{name}] source_id={source_id}")
            for r in conn.execute(
                """SELECT discipline, COUNT(*) FROM src_bj2012_norm
                    WHERE source_id = ? GROUP BY discipline
                    ORDER BY COUNT(*) DESC""", (source_id,)
            ).fetchall():
                print(f"     {r[0] or '(NULL)':<10} : {r[1]}")

        print(f"\n  装修二次拆分：命中章节数 = {decor_count}")

        # NULL 检查
        null_chap = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_chapter WHERE discipline IS NULL"
        ).fetchone()[0]
        null_norm = conn.execute(
            "SELECT COUNT(*) FROM src_bj2012_norm WHERE discipline IS NULL"
        ).fetchone()[0]
        print(f"\n  NULL discipline: chapter={null_chap}, norm={null_norm}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
