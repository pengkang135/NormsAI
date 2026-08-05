"""构建企业定额库（A册 建筑装饰）—— 试点：A.01 场地准备与土石方。

数据源：
- 框架：f:/BaiduSyncdisk/2.清单定额/3 清单规范/企业定额/A册 建筑装饰.sqlite
  提供 divisions / sub_divisions / items_gb / items_nrm 四张表。
- 定额数据：Norms-AI/db/北京2012_建设工程计价依据_预算定额.sqlite
  第一章 土石方工程 下的所有 Norm/Content/Consumption。

输出：Norms-AI/db/企业定额_A册_建筑装饰.sqlite
Schema 兼容"北京2012 预算定额"（chapter/Norm/Content/Consumption 表结构一致），
使得 Norms-AI/start.py 的 `_api_index_beijing / _api_items_beijing` 直接可用。

章节树按企业框架三级组织：
  L1: A.01 (division) → chap_code='01'
  L2: A.01.01 / A.01.02 / A.01.03 (sub_division) → chap_code='01.01' …
  L3: A.01.01.001 挖单独土方 (items_gb) → chap_code='01.01.001'
  Norm 挂在 L3 章节下。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORK_DB = Path(r"f:/BaiduSyncdisk/2.清单定额/3 清单规范/企业定额/A册 建筑装饰.sqlite")
BEIJING_DB = ROOT / "db" / "北京2012_建设工程计价依据_预算定额.sqlite"
OUT_DB = ROOT / "db" / "企业定额_A册_建筑装饰.sqlite"

# 试点范围：只导入 A.01 场地准备与土石方
FOCUS_DIVISION = "A.01"

# Beijing 2012 norm_ID → 企业 items_gb.code 映射表
# 建立基础：Beijing2012 房屋建筑与装饰工程 第一章 土石方工程 (chap_ID=101000000)
BJ_NORM_TO_GB = {
    # 平整场地及其他
    1: "A.01.03.001",   # 1-1 平整场地 人工
    2: "A.01.03.001",   # 1-2 平整场地 机械
    3: "A.01.03.001",   # 1-3 场地碾压
    4: "A.01.03.001",   # 1-4 原土打夯
    5: "A.01.03.001",   # 1-5 打钎拍底
    # 单独土方
    6: "A.01.01.001",   # 1-6 人工挖土方 运距1km以内
    7: "A.01.01.001",   # 1-7 机挖土方 运距1km以内
    # 基础土方(机挖不同深度)
    8: "A.01.02.001",   # 1-8 机挖土方 槽深5m 1km
    9: "A.01.02.001",   # 1-9 机挖土方 槽深5m 15km
    10: "A.01.02.001",  # 1-10 机挖土方 槽深13m 1km
    11: "A.01.02.001",  # 1-11 机挖土方 槽深13m 15km
    12: "A.01.02.001",  # 1-12 机挖土方 槽深13m外 1km
    13: "A.01.02.001",  # 1-13 机挖土方 槽深13m外 15km
    14: "A.01.02.001",  # 1-14 挖桩间土 1km
    15: "A.01.02.001",  # 1-15 挖桩间土 15km
    # 沟槽土方
    16: "A.01.02.002",  # 1-16 人工挖沟槽 1km
    17: "A.01.02.002",  # 1-17 人工坑底挖槽 1km
    18: "A.01.02.002",  # 1-18 机挖沟槽 1km
    19: "A.01.02.002",  # 1-19 机挖沟槽 15km
    # 基坑土方
    20: "A.01.02.001",  # 1-20 人工挖基坑 1km
    21: "A.01.02.001",  # 1-21 机挖基坑 1km
    22: "A.01.02.001",  # 1-22 机挖基坑 15km
    # 淤泥流砂
    23: "A.01.02.004",  # 1-23 挖淤泥流砂 人工
    24: "A.01.02.004",  # 1-24 挖淤泥流砂 机挖
    # 石方
    25: "A.01.01.002",  # 1-25 机械破碎 挖一般石方 (单独石方)
    26: "A.01.02.006",  # 1-26 机械破碎 挖沟槽石方
    27: "A.01.02.005",  # 1-27 机械破碎 挖基坑石方
    28: "A.01.01.002",  # 1-28 人工凿石 → 归到单独石方
    # 回填
    29: "A.01.02.007",  # 1-29 基础回填 松填
    30: "A.01.02.007",  # 1-30 基础回填 夯填
    31: "A.01.02.007",  # 1-31 灰土 2:8
    32: "A.01.02.007",  # 1-32 灰土 3:7
    33: "A.01.02.007",  # 1-33 级配砂石
    34: "A.01.02.007",  # 1-34 房心回填土
    35: "A.01.02.007",  # 1-35 地下室内回填土
    36: "A.01.02.007",  # 1-36 地下室内钢渣混凝土
    # 场地回填 → 归到 平整场地
    37: "A.01.03.001",  # 1-37 场地回填 素土
    38: "A.01.03.001",  # 1-38 场地回填 灰土 2:8
    39: "A.01.03.001",  # 1-39 场地回填 灰土 3:7
    40: "A.01.03.001",  # 1-40 场地回填 级配砂石
    # 土(石)方运输 → 余方弃置
    41: "A.01.03.002",
    42: "A.01.03.002",
    43: "A.01.03.002",
    44: "A.01.03.002",
    45: "A.01.03.002",
    46: "A.01.03.002",
    47: "A.01.03.002",
    48: "A.01.03.002",
    49: "A.01.03.002",
    # 淤泥流砂运输 → 挖淤泥流砂
    50: "A.01.02.004",
    51: "A.01.02.004",
    # 护壁泥浆运输 → 余方弃置
    52: "A.01.03.002",
    53: "A.01.03.002",
}


def open_src():
    fw = sqlite3.connect(str(FRAMEWORK_DB))
    fw.row_factory = sqlite3.Row
    bj = sqlite3.connect(str(BEIJING_DB))
    bj.row_factory = sqlite3.Row
    return fw, bj


def create_schema(con: sqlite3.Connection) -> None:
    """建立与北京2012兼容的 schema，并附加企业框架扩展字段。"""
    cur = con.cursor()

    # 1. chapter — 章节树
    cur.execute("""
        CREATE TABLE chapter (
            chap_ID INTEGER PRIMARY KEY,
            chap_PID INTEGER NOT NULL,
            chap_Name TEXT,
            chap_Content TEXT,
            chap_code TEXT,
            chap_Index TEXT
        )
    """)

    # 2. Norm — 定额条目
    cur.execute("""
        CREATE TABLE Norm (
            norm_ID INTEGER PRIMARY KEY,
            chap_ID INTEGER NOT NULL,
            chap_Code TEXT,
            norm_SortID INTEGER,
            norm_Specialty TEXT,
            norm_Code TEXT,
            norm_Name TEXT,
            norm_Units TEXT,
            norm_BaseUnits TEXT,
            norm_UnitsQuotiety REAL,
            norm_ManPrice REAL,
            norm_MaterialPrice REAL,
            norm_MachinePrice REAL,
            norm_OtherPrice REAL,
            norm_MainMaterialPrice REAL,
            norm_EquipmentPrice REAL,
            norm_AttachTag1 TEXT,
            norm_AttachTag INTEGER,
            norm_isEntity TEXT,
            norm_Tag INTEGER,
            norm_direct TEXT,
            norm_Alias TEXT,
            Norm_Content INT
        )
    """)

    # 3. Consumption — 人材机
    cur.execute("""
        CREATE TABLE Consumption (
            cons_ID INTEGER PRIMARY KEY,
            kind_ID INTEGER,
            kind_Code TEXT,
            cons_Code TEXT,
            cons_Alias TEXT,
            cons_Name TEXT,
            cons_Standard TEXT,
            cons_Units TEXT,
            cons_Price DECIMAL,
            cons_Market DECIMAL,
            cons_Supply REAL,
            cons_ThreeTag TEXT,
            cons_ThreeQuotiety REAL,
            cons_Style INTEGER,
            cons_UnitQuotiety INTEGER,
            cons_CompositeStyle INTEGER,
            cons_IsCalculate TEXT,
            cons_CalculateBasic TEXT
        )
    """)

    # 4. Content — 定额-人材机 关联
    cur.execute("""
        CREATE TABLE Content (
            cont_ID INTEGER PRIMARY KEY,
            norm_ID INTEGER NOT NULL,
            cons_ID INTEGER NOT NULL,
            cont_Amount REAL,
            cont_Type INTEGER,
            cont_IsMainMaterial TEXT,
            cont_IsCalculatePrice TEXT
        )
    """)

    # 5. enterprise_item — 企业框架 items_gb 元数据（原样保留供扩展）
    cur.execute("""
        CREATE TABLE enterprise_item (
            code TEXT PRIMARY KEY,
            division TEXT,
            sub_level3 TEXT,
            name TEXT,
            unit TEXT,
            item_feature TEXT,
            calc_rule TEXT,
            work_content TEXT,
            gb_ref TEXT,
            chap_ID INTEGER
        )
    """)

    cur.execute("CREATE INDEX idx_norm_chap ON Norm(chap_ID)")
    cur.execute("CREATE INDEX idx_content_norm ON Content(norm_ID)")
    cur.execute("CREATE INDEX idx_content_cons ON Content(cons_ID)")
    con.commit()


def _division_code_to_num(div: str) -> str:
    """A.01 → 01"""
    return div.split(".", 1)[1]


def build_chapters(dst: sqlite3.Connection, fw: sqlite3.Connection) -> dict[str, int]:
    """建立三级章节树，返回 items_gb.code → chap_ID 的映射。"""
    cur = dst.cursor()
    # L1: division
    div_row = fw.execute(
        "SELECT code, name, description FROM division WHERE code = ?",
        (FOCUS_DIVISION,),
    ).fetchone()
    if not div_row:
        raise RuntimeError(f"未在框架库中找到 division {FOCUS_DIVISION}")

    div_num = _division_code_to_num(div_row["code"])       # "01"
    div_chap_id = int(div_num) * 1_000_000                 # 1_000_000
    cur.execute(
        "INSERT INTO chapter (chap_ID, chap_PID, chap_Name, chap_Content, chap_code, chap_Index) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            div_chap_id,
            0,
            f"{div_row['code']} {div_row['name']}",
            div_row["description"] or "",
            div_num,
            div_num,
        ),
    )

    # L2: sub_division
    sub_chap_ids: dict[str, int] = {}  # sub_code → chap_ID
    subs = fw.execute(
        "SELECT sub_code, name FROM sub_division WHERE division_code = ? ORDER BY sub_code",
        (FOCUS_DIVISION,),
    ).fetchall()
    for s in subs:
        sub_chap_id = div_chap_id + int(s["sub_code"]) * 1000
        chap_code = f"{div_num}.{s['sub_code']}"
        cur.execute(
            "INSERT INTO chapter (chap_ID, chap_PID, chap_Name, chap_Content, chap_code, chap_Index) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                sub_chap_id,
                div_chap_id,
                f"{FOCUS_DIVISION}.{s['sub_code']} {s['name']}",
                "",
                chap_code,
                chap_code,
            ),
        )
        sub_chap_ids[s["sub_code"]] = sub_chap_id

    # L3: items_gb
    item_chap_ids: dict[str, int] = {}
    items = fw.execute(
        "SELECT code, division, sub_level3, name, unit, item_feature, calc_rule, work_content, gb_ref "
        "FROM enterprise_item WHERE division = ? ORDER BY code",
        (FOCUS_DIVISION,),
    ).fetchall()
    for it in items:
        # code like "A.01.01.001"
        parts = it["code"].split(".")
        if len(parts) != 4:
            continue
        seq = int(parts[3])
        parent = sub_chap_ids[it["sub_level3"]]
        item_chap_id = parent + seq
        chap_code = f"{div_num}.{it['sub_level3']}.{parts[3]}"

        # 把 项目特征/工作内容/计量规则 写入 chap_Content，供后续扩展渲染
        content_parts = []
        if it["item_feature"]:
            content_parts.append(f"【项目特征】{it['item_feature']}")
        if it["calc_rule"]:
            content_parts.append(f"【计量规则】{it['calc_rule']}")
        if it["work_content"]:
            content_parts.append(f"【工作内容】{it['work_content']}")
        if it["gb_ref"]:
            content_parts.append(f"【GB编码】{it['gb_ref']}")
        chap_content = "\n".join(content_parts)

        cur.execute(
            "INSERT INTO chapter (chap_ID, chap_PID, chap_Name, chap_Content, chap_code, chap_Index) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                item_chap_id,
                parent,
                f"{it['code']} {it['name']}",
                chap_content,
                chap_code,
                chap_code,
            ),
        )
        item_chap_ids[it["code"]] = item_chap_id

        cur.execute(
            "INSERT INTO enterprise_item (code, division, sub_level3, name, unit, "
            "item_feature, calc_rule, work_content, gb_ref, chap_ID) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                it["code"], it["division"], it["sub_level3"], it["name"], it["unit"],
                it["item_feature"], it["calc_rule"], it["work_content"], it["gb_ref"],
                item_chap_id,
            ),
        )

    dst.commit()
    return item_chap_ids


def copy_norms_and_deps(
    dst: sqlite3.Connection,
    bj: sqlite3.Connection,
    item_chap_ids: dict[str, int],
) -> tuple[int, int, int]:
    """按 BJ_NORM_TO_GB 拷贝定额/关联/消耗数据。返回 (norm_count, content_count, cons_count)"""
    cur = dst.cursor()

    # 收集需要迁移的 norm_ID 列表
    norm_ids = list(BJ_NORM_TO_GB.keys())
    placeholders = ",".join(["?"] * len(norm_ids))

    # 1. Norm — 逐条拷贝并改写 chap_ID
    norm_rows = bj.execute(
        f"SELECT * FROM Norm WHERE norm_ID IN ({placeholders})",
        norm_ids,
    ).fetchall()
    kept_norm_ids = []
    for r in norm_rows:
        gb_code = BJ_NORM_TO_GB.get(r["norm_ID"])
        if not gb_code:
            continue
        new_chap_id = item_chap_ids.get(gb_code)
        if new_chap_id is None:
            print(f"  [WARN] items_gb code {gb_code} 未建章节，跳过 norm_ID={r['norm_ID']}")
            continue
        cur.execute(
            """INSERT INTO Norm (
                norm_ID, chap_ID, chap_Code, norm_SortID, norm_Specialty,
                norm_Code, norm_Name, norm_Units, norm_BaseUnits, norm_UnitsQuotiety,
                norm_ManPrice, norm_MaterialPrice, norm_MachinePrice, norm_OtherPrice,
                norm_MainMaterialPrice, norm_EquipmentPrice,
                norm_AttachTag1, norm_AttachTag, norm_isEntity, norm_Tag,
                norm_direct, norm_Alias, Norm_Content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["norm_ID"], new_chap_id, gb_code, r["norm_SortID"], r["norm_Specialty"],
                r["norm_Code"], r["norm_Name"], r["norm_Units"], r["norm_BaseUnits"], r["norm_UnitsQuotiety"],
                r["norm_ManPrice"], r["norm_MaterialPrice"], r["norm_MachinePrice"], r["norm_OtherPrice"],
                r["norm_MainMaterialPrice"], r["norm_EquipmentPrice"],
                r["norm_AttachTag1"], r["norm_AttachTag"], r["norm_isEntity"], r["norm_Tag"],
                r["norm_direct"], r["norm_Alias"], r["Norm_Content"],
            ),
        )
        kept_norm_ids.append(r["norm_ID"])

    # 2. Content — 只保留 kept_norm_ids
    if not kept_norm_ids:
        dst.commit()
        return 0, 0, 0
    kp = ",".join(["?"] * len(kept_norm_ids))
    content_rows = bj.execute(
        f"SELECT * FROM Content WHERE norm_ID IN ({kp}) ORDER BY cont_ID",
        kept_norm_ids,
    ).fetchall()
    referenced_cons_ids = set()
    for r in content_rows:
        cur.execute(
            "INSERT INTO Content (cont_ID, norm_ID, cons_ID, cont_Amount, cont_Type, "
            "cont_IsMainMaterial, cont_IsCalculatePrice) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                r["cont_ID"], r["norm_ID"], r["cons_ID"], r["cont_Amount"], r["cont_Type"],
                r["cont_IsMainMaterial"], r["cont_IsCalculatePrice"],
            ),
        )
        referenced_cons_ids.add(r["cons_ID"])

    # 3. Consumption — 只保留被引用的
    if referenced_cons_ids:
        kc = ",".join(["?"] * len(referenced_cons_ids))
        cons_rows = bj.execute(
            f"SELECT * FROM Consumption WHERE cons_ID IN ({kc})",
            list(referenced_cons_ids),
        ).fetchall()
        for r in cons_rows:
            cur.execute(
                """INSERT INTO Consumption (
                    cons_ID, kind_ID, kind_Code, cons_Code, cons_Alias, cons_Name,
                    cons_Standard, cons_Units, cons_Price, cons_Market, cons_Supply,
                    cons_ThreeTag, cons_ThreeQuotiety, cons_Style, cons_UnitQuotiety,
                    cons_CompositeStyle, cons_IsCalculate, cons_CalculateBasic
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    r["cons_ID"], r["kind_ID"], r["kind_Code"], r["cons_Code"], r["cons_Alias"], r["cons_Name"],
                    r["cons_Standard"], r["cons_Units"], r["cons_Price"], r["cons_Market"], r["cons_Supply"],
                    r["cons_ThreeTag"], r["cons_ThreeQuotiety"], r["cons_Style"], r["cons_UnitQuotiety"],
                    r["cons_CompositeStyle"], r["cons_IsCalculate"], r["cons_CalculateBasic"],
                ),
            )

    dst.commit()
    return len(kept_norm_ids), len(content_rows), len(referenced_cons_ids)


def main() -> None:
    if OUT_DB.exists():
        OUT_DB.unlink()
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)

    fw, bj = open_src()
    dst = sqlite3.connect(str(OUT_DB))
    try:
        create_schema(dst)
        item_chap_ids = build_chapters(dst, fw)
        print(f"[OK] 建立章节：1 分部 + {len(item_chap_ids)} 分项")
        n, c, cs = copy_norms_and_deps(dst, bj, item_chap_ids)
        print(f"[OK] 迁移数据：{n} 条定额 / {c} 条 Content / {cs} 条 Consumption")
    finally:
        fw.close()
        bj.close()
        dst.close()

    print(f"\n[DONE] {OUT_DB}")


if __name__ == "__main__":
    main()
