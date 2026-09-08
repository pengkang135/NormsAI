# -*- coding: utf-8 -*-
"""重建 resource_master.resource_usage —— 五册 Consumption 到人材机主数据的使用台账。

价格库要按册导航、显示引用次数，跨 5 库 ATTACH 聚合太慢，预计算成一张表。
cons_Style / kind_Code 取分册视角的值：同一资源在 A 册是材料、在 B 册可能是主材。

各册数据更新后重跑。幂等：整表重建。

Usage:
    python scripts/build_resource_usage.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import DB_DIR

VOLS = {
    "A": "企业定额_A册_建筑装饰.sqlite",
    "B": "企业定额_B册_通用安装.sqlite",
    "C": "企业定额_C册_市政园林.sqlite",
    "D": "企业定额_D册_水运工程.sqlite",
    "E": "企业定额_E册_房屋修缮.sqlite",
}

SCHEMA = """
CREATE TABLE resource_usage (
  res_ID    INTEGER REFERENCES resource(res_ID),
  vol       TEXT,
  cons_ID   INTEGER,
  cons_Style   INTEGER,
  kind_Code    TEXT,
  cons_Name    TEXT,
  cons_Standard TEXT,
  cons_Units   TEXT,
  cons_Price   REAL,
  refs      INTEGER,
  PRIMARY KEY (res_ID, vol, cons_ID)
)
"""

QUERY = """
SELECT cs.master_res_ID, cs.cons_ID, cs.cons_Style, cs.kind_Code,
       cs.cons_Name, cs.cons_Standard, cs.cons_Units, cs.cons_Price,
       COUNT(ct.cont_ID)
FROM Consumption cs
LEFT JOIN Content ct ON ct.cons_ID = cs.cons_ID
GROUP BY cs.cons_ID
"""


def main():
    master = DB_DIR / "resource_master.sqlite"
    if not master.exists():
        sys.exit(f"主数据库不存在: {master}")

    rows = []
    unlinked = {}
    for vol, fname in VOLS.items():
        path = DB_DIR / fname
        if not path.exists():
            sys.exit(f"分册库不存在: {path}")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            n_vol = 0
            for r in conn.execute(QUERY):
                if r[0] is None:
                    unlinked[vol] = unlinked.get(vol, 0) + 1
                    continue
                rows.append((r[0], vol) + tuple(r[1:]))
                n_vol += 1
            print(f"  {vol} 册 {n_vol} 条")
        finally:
            conn.close()

    if unlinked:
        print(f"警告: master_res_ID 为空的条目 {unlinked}")

    conn = sqlite3.connect(master)
    conn.execute("DROP TABLE IF EXISTS resource_usage")
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO resource_usage "
        "(res_ID, vol, cons_ID, cons_Style, kind_Code, cons_Name, cons_Standard, "
        " cons_Units, cons_Price, refs) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE INDEX idx_usage_vol ON resource_usage(vol, cons_Style)")
    conn.execute("CREATE INDEX idx_usage_res ON resource_usage(res_ID)")
    conn.execute("CREATE INDEX idx_usage_kind ON resource_usage(kind_Code)")
    conn.commit()

    total, res_n = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT res_ID) FROM resource_usage").fetchone()
    print(f"\nresource_usage: {total} 行 / {res_n} 个资源")
    for r in conn.execute(
            "SELECT vol, COUNT(*), COUNT(DISTINCT res_ID), SUM(refs) "
            "FROM resource_usage GROUP BY 1 ORDER BY 1"):
        print(f"  {r[0]}: {r[1]} 条目 / {r[2]} 资源 / {r[3]} refs")
    conn.close()


if __name__ == "__main__":
    main()
