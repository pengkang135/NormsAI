"""
合并北京2021定额章节到现有A/C册层级 + 定额编号添加BJ12/BJ21前缀。

操作:
1. 将2021章节节点重新挂载到现有A/C册章节下
2. 删除空的2021根章节
3. 北京2012定额编号添加BJ12.前缀，北京2021定额编号添加BJ21.前缀
"""
import sqlite3
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"

A_DB = DB_DIR / "企业定额_A册_建筑装饰.sqlite"
C_DB = DB_DIR / "企业定额_C册_市政园林.sqlite"

# A册: 2021章节ID → 现有A册章节ID
A_MAP = {
    131000000: 1000000,   # 01.01 土石方工程 → A.01
    132000000: 2000000,   # 01.02 地基处理与边坡支护 → A.02
    133000000: 3000000,   # 01.03 桩基工程 → A.03
    134000000: 4000000,   # 01.04 砌筑工程 → A.04 钢筋混凝土及钢筋
    135000000: 4000000,   # 01.05 混凝土及钢筋混凝土 → A.04
    136000000: 6000000,   # 01.06 金属结构工程 → A.06 钢结构
    137000000: 8000000,   # 01.07 木结构工程 → A.08 木结构与木构件
    138000000: 13000000,  # 01.08 门窗工程 → A.13
    139000000: 10000000,  # 01.09 屋面及防水 → A.10 屋面工程
    140000000: 12000000,  # 01.10 保温隔热防腐 → A.12
    141000000: 20000000,  # 01.11 楼地面装饰 → A.20
    142000000: 21000000,  # 01.12 墙柱面装饰与幕墙 → A.21
    143000000: 22000000,  # 01.13 天棚工程 → A.22
    144000000: 23000000,  # 01.14 油漆涂料裱糊 → A.23
    145000000: 24000000,  # 01.15 其他装饰工程 → A.24
    146000000: 33000000,  # 01.16 措施项目 → A.33
}
A_ROOTS_TO_DELETE = [130000000]  # 2021根章节 "房屋建筑与装饰工程"

# C册: 2021章节ID → 现有C册章节ID
C_MAP = {
    # 市政 第一~三册 (root 160M, offset=60M)
    170000000: 1000000,   # 04.01 通用项目 → C.01 土石方工程
    180000000: 2000000,   # 04.02 道路工程 → C.02 道路工程
    190000000: 3000000,   # 04.03 桥涵工程 → C.03 桥涵工程

    # 市政 第四册 上册 (root 230M, offset=130M) — 管道/给排水
    231000000: 4000000,   # 01.01 管道安装工程 → C.04 给排水工程
    232000000: 4000000,   # 01.02 管件与阀门 → C.04
    233000000: 4000000,   # 01.03 给水管道铺设 → C.04
    234000000: 4000000,   # 01.04 给水管道附属构筑物 → C.04
    235000000: 4000000,   # 01.05 排水管道工程 → C.04
    236000000: 4000000,   # 01.06 排水管道附属构筑物 → C.04

    # 市政 第四册 下册 (root 300M, offset=200M)
    310000000: 4000000,   # 04.01 管道附属工程 → C.04

    # 市政 第五册 (root 370M, offset=270M)
    380000000: 6000000,   # 04.01 水处理工程 → C.06 水处理工程

    # 园林 (root 840M, offset=340M)
    841000000: 20000000,  # 05.01 土方工程 → C.20 绿化工程
    842000000: 20000000,  # 05.02 绿化工程 → C.20
    843000000: 21000000,  # 05.03 园路园桥 → C.21 园路园桥
    844000000: 22000000,  # 05.04 园林景观 → C.22 园林景观
    845000000: 33000000,  # 05.05 模板工程 → C.33 措施项目
}
C_ROOTS_TO_DELETE = [160000000, 230000000, 300000000, 370000000, 840000000]


def backup_db(db_path):
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = backup_dir / f"{db_path.stem}.pre-merge-{ts}.bak"
    shutil.copy2(db_path, bak)
    print(f"  [BACKUP] {bak.name}")
    return bak


def merge_chapters(conn, chapter_map, roots_to_delete):
    """将chapter_map中的章节重新挂载到目标章节下，然后删除空根章节"""
    for src_id, dst_id in chapter_map.items():
        conn.execute("UPDATE chapter SET chap_PID=? WHERE chap_ID=?", (dst_id, src_id))

    for root_id in roots_to_delete:
        conn.execute("DELETE FROM chapter WHERE chap_ID=?", (root_id,))

    conn.commit()
    return len(chapter_map)


def prefix_norm_codes(conn):
    """为北京2012定额编号加BJ12.前缀，北京2021定额编号加BJ21.前缀"""
    # 通过norm_source表识别来源
    bj12 = conn.execute(
        """UPDATE Norm SET norm_Code = 'BJ12.' || norm_Code
           WHERE norm_ID IN (
               SELECT ns.norm_ID FROM norm_source ns
               WHERE ns.source_lib LIKE '%2012%'
           )
           AND norm_Code NOT LIKE 'BJ12.%'"""
    ).rowcount

    bj21 = conn.execute(
        """UPDATE Norm SET norm_Code = 'BJ21.' || norm_Code
           WHERE norm_ID IN (
               SELECT ns.norm_ID FROM norm_source ns
               WHERE ns.source_lib LIKE '%2021%'
           )
           AND norm_Code NOT LIKE 'BJ21.%'"""
    ).rowcount

    conn.commit()
    return bj12, bj21


def verify(conn, label):
    """验证结果"""
    roots = conn.execute(
        "SELECT chap_ID, chap_code, chap_Name FROM chapter WHERE chap_PID=0 ORDER BY chap_ID"
    ).fetchall()
    total_chapters = conn.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]
    total_norms = conn.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]

    print(f"\n  [{label}] 根章节: {len(roots)}, 总章节: {total_chapters}, 总定额: {total_norms}")

    # 检查是否有未映射的2021章节(仍挂在已删除根章节下)
    orphan = conn.execute(
        "SELECT COUNT(*) FROM chapter WHERE chap_PID IN ("
        "130000000, 160000000, 230000000, 300000000, 370000000, 840000000"
        ")"
    ).fetchone()[0]
    if orphan > 0:
        print(f"  [WARN] 仍有 {orphan} 个章节挂在已删除根章节下!")
    else:
        print(f"  [OK] 无孤立章节")

    # 检查编号前缀
    bj12 = conn.execute(
        "SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ12.%'"
    ).fetchone()[0]
    bj21 = conn.execute(
        "SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ21.%'"
    ).fetchone()[0]
    other = total_norms - bj12 - bj21
    print(f"  BJ12前缀: {bj12}, BJ21前缀: {bj21}, 其他: {other}")

    # 显示新结构
    print(f"  根章节列表:")
    for r in roots:
        children = conn.execute(
            "SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (r[0],)
        ).fetchone()[0]
        print(f"    {r[2]} (ID={r[0]}, children={children})")


def main():
    print("=" * 60)
    print("合并2021定额章节 + 编号前缀")
    print("=" * 60)

    # ---- Backups ----
    print("\n[1/4] 备份数据库...")
    for db in [A_DB, C_DB]:
        backup_db(db)

    # ---- A册 ----
    print("\n[2/4] 处理A册...")
    a = sqlite3.connect(str(A_DB))
    n = merge_chapters(a, A_MAP, A_ROOTS_TO_DELETE)
    print(f"  合并章节: {n}")
    bj12, bj21 = prefix_norm_codes(a)
    print(f"  编号前缀: BJ12={bj12}, BJ21={bj21}")
    verify(a, "A册")
    a.close()

    # ---- C册 ----
    print("\n[3/4] 处理C册...")
    c = sqlite3.connect(str(C_DB))
    n = merge_chapters(c, C_MAP, C_ROOTS_TO_DELETE)
    print(f"  合并章节: {n}")
    bj12, bj21 = prefix_norm_codes(c)
    print(f"  编号前缀: BJ12={bj12}, BJ21={bj21}")
    verify(c, "C册")
    c.close()

    print("\n[4/4] 完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
