"""把 PK 土建定额库 2026.06 追加导入到企业定额 A 册（建筑装饰）。

前置：先跑 build_enterprise_norms_A_full.py 建好北京2012 基础版 A 册。

流程：
- 读 PK 库 (boq_pk_civil_202606.sqlite) 的 chapter + boq_item + boq_resource_def + boq_resource_qty
- 将 PK 的 chapter 3 级组（如 D.a.01 砖）映射到 A 册的 items_gb 编号
- 把 boq_item / resource_def / resource_qty 转成 Beijing 兼容的 Norm / Consumption / Content 格式
- ID 冲突：PK 的 boq_item.id 和 resource_def.id 都加 20_000_000 offset
  （北京2012 用 0-2000万区间；PK 用 2000-3000万区间；将来其他源用 3000-4000万等）
- 同时写入 norm_source 表标注 source_lib = "PK土建定额库_2026.06"

只导入 A 册相关分部：A-Q, V, W（排除 R/S/T/U 市政园林、X 配比材料）。
"""

from __future__ import annotations
import sqlite3
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PK_DB = ROOT / "db" / "boq_pk_civil_202606.sqlite"
DST_DB = ROOT / "db" / "企业定额_A册_建筑装饰.sqlite"

SOURCE_LIB = "PK土建定额库_2026.06"
NORM_ID_OFFSET = 20_000_000
CONS_ID_OFFSET = 20_000_000

# PK level-3 chapter code → A册 items_gb.code
# code 格式如 "A.a.01" ，映射到 A册 分项如 "A.01.03.001"
PK_CHAP_TO_GB: dict[str, str] = {
    # ── A 土石方工程 → A.01 ──
    "A.a.01": "A.01.02.001",  # 土石方 (含挖单独/基坑/沟槽/淤泥/回填等，默认基坑；将来可细化)
    "A.b.01": "A.01.03.001",  # 种植土 → 平整场地 (fallback; 屋顶花园种植土层)

    # ── B 地基处理 → A.02 ──
    "B.a.01": "A.02.01.001",  # 地基处理 → 换填垫层 default (含木制桩/换填/钢板桩)
    "B.b.01": "A.02.01.008",  # 喷射注浆 → 旋喷桩复合地基
    "B.b.02": "A.02.02.007",  # 锚杆注浆 → 锚杆(锚索)
    "B.b.03": "A.02.02.009",  # 护坡 → 喷射混凝土

    # ── C 桩基工程 → A.03 ──
    "C.a.03": "A.03.01.001",  # 预制桩 → 预制钢筋混凝土实心桩
    "C.b.01": "A.03.02.001",  # 钻孔浇灌一体 → 泥浆护壁成孔灌注桩
    "C.b.02": "A.03.02.001",  # 钢护筒和泥浆池
    "C.b.03": "A.03.02.001",  # 钻孔
    "C.b.04": "A.03.02.001",  # 浇筑
    "C.c.01": "A.03.01.005",  # 截桩头
    "C.c.02": "A.03.02.007",  # 试验 → 声测管 (fallback)

    # ── D 砌筑工程 → A.06 ──
    "D.a.01": "A.06.01.002",  # 砖砌体 砖 → 实心砖墙 (default; 含基础/柱等)
    "D.a.02": "A.06.02.001",  # 砖砌体 砌块 → 砌块墙
    "D.a.03": "A.06.01.008",  # 零星砌体 → 零星砌砖
    "D.a.04": "A.06.03.003",  # 石砌体 → 石墙
    "D.b.01": "A.21.06.001",  # 轻质隔墙
    "D.c.01": "A.06.01.002",  # 围墙 → 实心砖墙 (default)

    # ── E 混凝土工程 → A.04 现浇 + A.05 预制 ──
    "E.a.01": "A.04.02.001",  # 基础及地下 → 独立基础 default
    "E.b.01": "A.04.06.013",  # 主体结构 → 实心楼板 default
    "E.b.02": "A.04.09.025",  # 其他混凝土构件 → 零星现浇构件
    "E.b.03": "A.04.08.021",  # 二次结构 → 构造柱 (default; 含圈梁/过梁/填充)
    "E.c.01": "A.04.09.025",  # 钢筋模板混凝土全包 → 零星
    "E.d.01": "A.05.01.001",  # 一般预制 → 矩形柱 default
    "E.e.01": "A.05.02.001",  # 装配式预制 → 实心柱 default

    # ── F 模板工程 → A.04.12 ──
    "F.a.01": "A.04.12.002",  # 基础模板
    "F.a.02": "A.04.12.005",  # 结构模板 → 墙面模板 default
    "F.a.03": "A.04.12.014",  # 其他模板 → 零星现浇构件模板
    "F.a.04": "A.04.12.011",  # 二次结构模板 → 构造柱模板
    "F.b.01": "A.04.12.007",  # 盘扣式支撑 → 楼板模板 default

    # ── G 钢筋工程 → A.04.13/14 ──
    "G.a.01": "A.04.13.001",  # 基础钢筋
    "G.a.02": "A.04.13.005",  # 主体钢筋 → 现浇混凝土梁钢筋 default
    "G.a.03": "A.04.13.001",  # 钢筋制安 → 基础钢筋 (fallback)
    "G.a.04": "A.04.14.020",  # 钢筋网片
    "G.a.05": "A.04.13.001",  # 钢筋制安含搭接
    "G.b.01": "A.04.14.024",  # 接头和支撑 → 螺栓
    "G.b.02": "A.04.14.026",  # 防震 → 结构抗(隔)震支座
    "G.c.01": "A.04.14.017",  # 砌体钢筋 → 砌体工程内配钢筋
    "G.c.02": "A.04.13.010",  # 非受力混凝土结构钢筋 → 二次结构钢筋

    # ── H 金属结构 → A.07 ──
    "H.a.01": "A.07.01.001",  # 钢结构件 → 钢网架 default (含各种钢构件)
    "H.b.01": "A.07.07.010",  # 其他钢构件 → 零星钢构件 default
    "H.b.02": "A.07.07.003",  # 钢檩条
    "H.c.01": "A.04.14.025",  # 埋件螺栓铁件 → 预埋铁件 default
    "H.d.01": "A.23.04.005",  # 钢结构表面处理 → 金属面喷刷防火涂料 default
    "H.e.01": "A.07.09.001",  # 金属制品 → 金属百页护栏 default

    # ── I 木结构 → A.08 (PK 数据为空，跳过) ──

    # ── J 门窗栏杆 → A.13 ──
    "J.b.01": "A.13.01.001",  # 木门
    "J.b.02": "A.13.02.001",  # 金属门
    "J.b.03": "A.13.03.001",  # 卷帘门
    "J.b.04": "A.13.04.001",  # 厂库房大门、特种门
    "J.b.05": "A.13.05.001",  # 其他门
    "J.b.06": "A.13.08.001",  # 门窗套 → 木门窗套 default
    "J.c.01": "A.13.01.020",  # 五金件 → 门五金配件 (新扩展)
    "J.d.01": "A.13.07.001",  # 窗
    "J.d.02": "A.13.10.001",  # 窗帘、窗帘盒、轨
    "J.e.01": "A.14.01.001",  # 构件式幕墙 → 构件式玻璃幕墙
    "J.e.02": "A.14.01.006",  # 其他幕墙 → 全玻(无框玻璃)幕墙
    "J.e.03": "A.14.01.008",  # 轻钢雨棚采光顶 → 幕墙开启扇 (fallback)
    "J.f.03": "A.13.20.001",  # 栏杆

    # ── K 防水及屋面 → A.10 + A.11 ──
    "K.a.01": "A.11.01.004",  # 刚性层
    "K.a.02": "A.11.01.002",  # 涂料防水 → 屋面涂膜防水
    "K.a.03": "A.11.01.001",  # 卷材防水 → 屋面卷材防水
    "K.b.03": "A.10.01.005",  # 瓦屋面 (虽名称是瓦，实为金属屋面) → 金属板幕墙顶
    "K.c.03": "A.10.01.002",  # 轻钢雨棚采光顶 → 阳光板屋面 default
    "K.d.01": "A.10.01.007",  # 排水沟 → 屋面成品天沟、檐沟
    "K.d.02": "A.11.01.005",  # 排水管
    "K.d.03": "A.11.04.003",  # 止水带变形缝

    # ── L 保温隔热防腐 → A.12 ──
    "L.a.01": "A.12.01.003",  # 保温隔热 → 保温隔热墙面 default
    "L.b.01": "A.12.03.001",  # 其他防腐 → 隔离层防腐 default
    "L.c.01": "A.12.02.001",  # 防腐面层 → 防腐混凝土面层 default

    # ── M 楼地面 → A.20 ──
    "M.a.01": "A.20.01.006",  # 水泥找平基层 → 平面砂浆找平层
    "M.a.02": "A.20.01.001",  # 水泥混凝土面层 → 水泥砂浆楼地面
    "M.b.01": "A.20.02.003",  # 瓷砖地面 → 块料楼地面
    "M.b.02": "A.20.02.001",  # 石材地面
    "M.b.03": "A.20.04.002",  # 木材地面 → 竹、木(复合)地板
    "M.b.04": "A.20.08.004",  # 地面其他装饰 → 水泥砂浆零星
    "M.c.01": "A.20.03.001",  # 橡塑卷材面层 → 橡塑板楼地面
    "M.d.01": "A.20.01.004",  # 涂料地面 → 耐磨楼地面 (fallback for 环氧/固化剂)
    "M.e.01": "A.20.09.001",  # 其他材料面层 → 架空地板 (防静电)
    "M.f.01": "A.20.05.001",  # 踢脚线 → 水泥砂浆踢脚线 default
    "M.g.01": "A.20.06.001",  # 楼梯台阶面层 → 水泥砂浆楼梯 default
    "M.h.01": "A.20.08.005",  # 停车场装饰 → 车库标线、标识 default

    # ── N 墙面 → A.21 ──
    "N.a.01": "A.21.01.001",  # 墙面基层抹灰 → 墙、柱面一般抹灰
    "N.a.02": "A.21.01.002",  # 装饰抹灰 → 墙、柱面装饰抹灰
    "N.a.03": "A.21.02.001",  # 抹灰线条 → 零星项目一般抹灰
    "N.b.01": "A.21.03.003",  # 瓷砖 → 块料墙、柱面
    "N.b.02": "A.21.03.001",  # 石材 → 石材墙、柱面
    "N.b.03": "A.14.01.003",  # 幕墙 → 构件式金属板幕墙
    "N.b.04": "A.21.05.001",  # 装饰板材 → 墙、柱面装饰板
    "N.b.05": "A.21.05.004",  # 软包造型 → 墙、柱面软包
    "N.b.06": "A.21.05.005",  # 功能板材 → 保温装饰一体板

    # ── O 天棚 → A.22 ──
    "O.a.01": "A.22.02.022",  # 石膏板 → 吊顶面板 (企业扩展)
    "O.a.02": "A.22.02.022",  # 矿棉板 → 吊顶面板
    "O.a.06": "A.22.01.001",  # 天棚抹灰
    "O.b.01": "A.22.02.022",  # 成品扣板 → 吊顶面板
    "O.b.02": "A.22.02.004",  # 特殊吊顶 → 格栅吊顶 default (含格栅/吊筒/藤条/织物/网架)
    "O.c.01": "A.22.02.020",  # 吊顶配套 → 平吊龙骨 (吊顶检查孔/通风百叶/龙骨)
    "O.c.02": "A.22.03.001",  # 吊顶造型 → 成品装饰带 default
    "O.c.03": "A.13.10.001",  # 窗帘

    # ── P 油漆涂料裱糊 → A.23 ──
    "P.a.01": "A.23.03.003",  # 基层处理 → 刮腻子
    "P.a.02": "A.23.04.010",  # 内墙涂料
    "P.a.03": "A.23.04.002",  # 天棚涂料
    "P.a.04": "A.23.04.001",  # 外墙涂料
    "P.b.01": "A.23.01.004",  # 木油漆 → 木材面油漆 (fallback; 含各类木质件)
    "P.c.01": "A.23.02.003",  # 金属面油漆
    "P.d.01": "A.23.03.001",  # 抹灰面油漆
    "P.e.01": "A.23.04.001",  # 喷刷面油漆 → 墙面喷刷涂料 default
    "P.f.01": "A.23.05.001",  # 裱糊 → 墙纸裱糊

    # ── Q 其他装饰 → A.24 ──
    "Q.a.01": "A.24.05.002",  # 洁具 → 洗厕配件 default
    "Q.b.01": "A.24.01.001",  # 橱柜 → 装饰柜 default
    "Q.c.01": "A.24.07.001",  # 旗杆招牌灯箱 → 平面、箱式招牌 default

    # ── F.e.01 模板周转参数 (顶级独立组) → A.33.01 措施 ──
    "F.e.01": "A.33.01.001",  # 模板周转参数
    # ── I.e.01 木结构 (顶级独立组) → A.08 ──
    "I.e.01": "A.08.02.001",  # 木结构 (default 木柱; 含木屋架/梁/檩/楼梯/木基层)

    # ── V 措施费 → A.33.01 ──
    "V.a.01": "A.33.01.001",  # 扣件式脚手架
    "V.b.01": "A.33.01.001",  # 盘扣式脚手架
    "V.c.01": "A.33.01.001",  # 门件式脚手架 室外
    "V.c.02": "A.33.01.001",  # 门件式脚手架 室内
}


def load_a_items_gb_map(dst: sqlite3.Connection) -> dict[str, int]:
    """从 A册 DB 加载 items_gb.code → chap_ID 映射"""
    cur = dst.cursor()
    m = {}
    for r in cur.execute("SELECT code, chap_ID FROM enterprise_item"):
        m[r[0]] = r[1]
    return m


def import_pk_to_a() -> None:
    if not DST_DB.exists():
        print(f"[ERR] {DST_DB} 不存在，请先运行 build_enterprise_norms_A_full.py")
        return

    # 备份 A 册当前状态
    backup_dir = DST_DB.parent / "backup"
    backup_dir.mkdir(exist_ok=True)
    bak = backup_dir / f"{DST_DB.stem}.pre-pk-import-{int(time.time())}.bak"
    shutil.copy2(DST_DB, bak)
    print(f"[BACKUP] backup/{bak.name}")

    pk = sqlite3.connect(str(PK_DB)); pk.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(DST_DB)); dst.row_factory = sqlite3.Row
    cur = dst.cursor()
    import_time = datetime.now().isoformat(timespec="seconds")

    item_chap_ids = load_a_items_gb_map(dst)
    print(f"[LOAD] A 册当前 items_gb: {len(item_chap_ids)} 个")

    # 检查未映射的 items_gb 目标
    unresolved = [gb for gb in PK_CHAP_TO_GB.values() if gb not in item_chap_ids]
    if unresolved:
        print(f"[WARN] {len(set(unresolved))} 个映射目标在 A 册不存在:")
        for gb in set(unresolved):
            print(f"  {gb}")
        return

    # 找 PK chapter.id → chapter.code
    pk_chap_map = {r[0]: r[1] for r in pk.execute("SELECT id, code FROM chapter")}

    # 找所有 PK boq_item，按 chapter_id 分组
    pk_boq_items = pk.execute("""
        SELECT * FROM boq_item ORDER BY chapter_id, sort_order
    """).fetchall()

    # 只处理映射覆盖的 chapter
    kept_boq_ids: list[int] = []
    skipped_out_of_scope = 0
    unmapped_chapters: set[str] = set()

    for item in pk_boq_items:
        pk_chap_code = pk_chap_map.get(item["chapter_id"])
        if not pk_chap_code:
            continue
        gb_code = PK_CHAP_TO_GB.get(pk_chap_code)
        if not gb_code:
            # PK chapter 在映射表外（如 R/S/T/U/X）
            top_letter = pk_chap_code.split(".")[0]
            if top_letter in ("R", "S", "T", "U", "W", "X"):
                skipped_out_of_scope += 1
            else:
                unmapped_chapters.add(pk_chap_code)
            continue

        target_chap_id = item_chap_ids[gb_code]
        new_norm_id = NORM_ID_OFFSET + item["id"]

        # 转 boq_item → Norm
        base = (item["labour"] or 0) + (item["materials"] or 0) + (item["mech"] or 0)
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
                new_norm_id, target_chap_id, gb_code, item["sort_order"], "土建",
                item["code"], item["name"], item["unit"], item["unit"], 1.0,
                item["labour"], item["materials"], item["mech"], 0.0,
                0.0, 0.0,
                "PK", 1, "1", 0,
                None, None, item["work_content"],
            ),
        )

        # 写 norm_source 溯源
        cur.execute(
            """INSERT INTO norm_source (
                norm_ID, source_lib, source_norm_id, source_norm_code,
                source_chap_id, source_chap_name, source_chap_path, source_book, import_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_norm_id, SOURCE_LIB, item["id"], item["code"],
                item["chapter_id"], pk_chap_code, f"PK土建定额库 > {pk_chap_code}", "PK土建",
                import_time,
            ),
        )
        kept_boq_ids.append(item["id"])

    print(f"[OK] 导入 PK boq_item: {len(kept_boq_ids)} 条")
    if skipped_out_of_scope:
        print(f"[SKIP] R/S/T/U/W/X 分部超范围: {skipped_out_of_scope} 条")
    if unmapped_chapters:
        print(f"[WARN] 未映射 chapter: {len(unmapped_chapters)}")
        for c in sorted(unmapped_chapters):
            print(f"  {c}")

    # 转 boq_resource_def → Consumption
    n_cons = 0
    for r in pk.execute("SELECT * FROM boq_resource_def").fetchall():
        new_cons_id = CONS_ID_OFFSET + r["id"]
        cur.execute(
            """INSERT INTO Consumption VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_cons_id, 0, r["col_letter"], r["resource_name"],
                None, r["resource_name"], "", r["resource_unit"],
                r["unit_price"], r["unit_price"], 1.0,
                "", 1.0, 0, 1,
                0, "0", "",
            ),
        )
        n_cons += 1
    print(f"[OK] 导入 PK resource_def → Consumption: {n_cons} 条")

    # 转 boq_resource_qty → Content
    n_content = 0
    kept_set = set(kept_boq_ids)
    for r in pk.execute("SELECT * FROM boq_resource_qty").fetchall():
        # PK schema: boq_resource_qty(id, boq_item_id, resource_def_id, quantity)
        try:
            boq_item_id = r["boq_item_id"] if "boq_item_id" in r.keys() else r[1]
            resource_id = r["resource_def_id"] if "resource_def_id" in r.keys() else r[2]
            qty = r["quantity"] if "quantity" in r.keys() else r[3]
        except (KeyError, IndexError):
            continue
        if boq_item_id not in kept_set:
            continue
        cur.execute(
            """INSERT INTO Content (
                norm_ID, cons_ID, cont_Amount, cont_Type,
                cont_IsMainMaterial, cont_IsCalculatePrice
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                NORM_ID_OFFSET + boq_item_id,
                CONS_ID_OFFSET + resource_id,
                qty, 0, "0", "1",
            ),
        )
        n_content += 1
    print(f"[OK] 导入 PK resource_qty → Content: {n_content} 条")

    dst.commit()

    # 汇总
    total_norm = cur.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    total_src = cur.execute("SELECT COUNT(*) FROM norm_source").fetchone()[0]
    src_dist = cur.execute(
        "SELECT source_lib, COUNT(*) FROM norm_source GROUP BY source_lib"
    ).fetchall()
    print(f"\n[DONE] A册 现有 Norm: {total_norm} / norm_source: {total_src}")
    print("       来源库分布:")
    for lib, cnt in src_dist:
        print(f"         {lib}: {cnt} 条")

    pk.close(); dst.close()


if __name__ == "__main__":
    import_pk_to_a()
