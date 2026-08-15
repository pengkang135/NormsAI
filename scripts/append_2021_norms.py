"""
导入北京2021预算消耗量标准定额到企业定额A/C册。

数据源: F:\BaiduSyncdisk\2.清单定额\1 预算定额\7 北京定额21\21定额房建市政园林\
  - 01_房建装饰 → A册 (1,963 norms)
  - 04_市政1-3 → C册 (519 norms)
  - 04_市政4上 → C册 (1,453 norms)
  - 04_市政4下 → C册 (1,136 norms)
  - 04_市政5 → C册 (614 norms)
  - 05_园林 → C册 (1,026 norms)

总计: 1,963 (A) + 3,748 (C) = 5,711 norms
"""
import sqlite3
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
SRC_DIR = Path(r"F:\BaiduSyncdisk\2.清单定额\1 预算定额\7 北京定额21\21定额房建市政园林")

A_DB = DB_DIR / "企业定额_A册_建筑装饰.sqlite"
C_DB = DB_DIR / "企业定额_C册_市政园林.sqlite"

SOURCE_LIB = "北京2021_预算消耗量标准"

# Each source DB gets its own offset to avoid any ID collision
# Source chapters are in 100M-137M (span ~37M); offsets need >37M gaps.
# Existing C册 clusters: 200M-211M (仿古) and 2.0B-2.6B (城市轨道).
# Chosen offsets: 60M/130M/200M/270M/340M → chapters at 160M/230M/300M/370M/840M.
IMPORTS = [
    # (target_db, src_filename, offset, source_book)
    (A_DB, "01_北京2021_房屋建筑与装饰工程预算消耗量标准V2.sqlite", 30_000_000, "房屋建筑与装饰工程"),
    (C_DB, "04_北京2021_市政工程预算消耗量标准  第一~三册V2.sqlite", 60_000_000, "市政工程 第一~三册"),
    (C_DB, "04_北京2021_市政工程预算消耗量标准  第四册 上册V2.sqlite", 130_000_000, "市政工程 第四册 上册"),
    (C_DB, "04_北京2021_市政工程预算消耗量标准  第四册 下册V2.sqlite", 200_000_000, "市政工程 第四册 下册"),
    (C_DB, "04_北京2021_市政工程预算消耗量标准  第五册V2.sqlite", 270_000_000, "市政工程 第五册"),
    (C_DB, "05 园林绿化工程预算消耗量标准V2.sqlite", 340_000_000, "园林绿化工程"),
]


def backup_db(db_path: Path):
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir(exist_ok=True)
    bak = backup_dir / f"{db_path.stem}.pre-2021-{int(time.time())}.bak"
    shutil.copy2(db_path, bak)
    print(f"  [BACKUP] {bak.name}")


def get_descendant_ids(conn, root_ids):
    all_ids = set(root_ids)
    prev = 0
    while len(all_ids) > prev:
        prev = len(all_ids)
        placeholders = ",".join("?" * len(all_ids))
        new = conn.execute(
            f"SELECT chap_ID FROM chapter WHERE chap_PID IN ({placeholders})",
            list(all_ids),
        ).fetchall()
        for r in new:
            all_ids.add(r[0])
    return all_ids


def build_chapter_path(conn, chap_id):
    chain = []
    cid = chap_id
    while cid and cid != 0:
        r = conn.execute(
            "SELECT chap_PID, chap_Name FROM chapter WHERE chap_ID=?", (cid,)
        ).fetchone()
        if not r:
            break
        chain.append(r[1])
        cid = r[0]
    chain.reverse()
    return " > ".join(chain)


def copy_chapter_tree(src_conn, dst_conn, root_ids, offset):
    dst_cur = dst_conn.cursor()
    all_ids = get_descendant_ids(src_conn, root_ids)
    placeholders = ",".join("?" * len(all_ids))
    chapters = src_conn.execute(
        f"SELECT * FROM chapter WHERE chap_ID IN ({placeholders}) ORDER BY chap_ID",
        list(all_ids),
    ).fetchall()

    count = 0
    for r in chapters:
        new_id = r["chap_ID"] + offset
        new_pid = r["chap_PID"] + offset if r["chap_PID"] and r["chap_PID"] != 0 else 0
        dst_cur.execute(
            "INSERT INTO chapter VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id, new_pid, r["chap_Name"], r["chap_Content"],
                r["chap_code"], r["chap_Index"], None, None,
            ),
        )
        count += 1
    dst_conn.commit()
    return count


def copy_norms_data(src_conn, dst_conn, chap_ids, offset, source_book):
    dst_cur = dst_conn.cursor()
    import_time = datetime.now().isoformat(timespec="seconds")
    stats = {"norms": 0, "contents": 0, "cons": 0}

    placeholders = ",".join("?" * len(chap_ids))
    norms = src_conn.execute(
        f"SELECT * FROM Norm WHERE chap_ID IN ({placeholders}) ORDER BY norm_ID",
        list(chap_ids),
    ).fetchall()

    kept_src_norm_ids = []
    for r in norms:
        new_norm_id = r["norm_ID"] + offset
        new_chap_id = r["chap_ID"] + offset
        dst_cur.execute(
            """INSERT INTO Norm VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )""",
            (
                new_norm_id, new_chap_id, r["chap_Code"], r["norm_SortID"],
                r["norm_Specialty"], r["norm_Code"], r["norm_Name"],
                r["norm_Units"], r["norm_BaseUnits"], r["norm_UnitsQuotiety"],
                r["norm_ManPrice"], r["norm_MaterialPrice"], r["norm_MachinePrice"],
                r["norm_OtherPrice"], r["norm_MainMaterialPrice"], r["norm_EquipmentPrice"],
                r["norm_AttachTag1"], r["norm_AttachTag"], r["norm_isEntity"],
                r["norm_Tag"], r["norm_direct"], r["norm_Alias"], r["Norm_Content"],
                None, None,
            ),
        )
        chap_path = build_chapter_path(src_conn, r["chap_ID"])
        chap_name_row = src_conn.execute(
            "SELECT chap_Name FROM chapter WHERE chap_ID=?", (r["chap_ID"],)
        ).fetchone()
        chap_name = chap_name_row["chap_Name"] if chap_name_row else ""
        dst_cur.execute(
            "INSERT INTO norm_source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_norm_id, SOURCE_LIB, r["norm_ID"], r["norm_Code"],
                r["chap_ID"], chap_name, chap_path, source_book, import_time,
            ),
        )
        kept_src_norm_ids.append(r["norm_ID"])
        stats["norms"] += 1

    if not kept_src_norm_ids:
        return stats

    BATCH = 500
    referenced_cons = set()
    for i in range(0, len(kept_src_norm_ids), BATCH):
        batch = kept_src_norm_ids[i : i + BATCH]
        kp = ",".join("?" * len(batch))
        for r in src_conn.execute(
            f"SELECT * FROM Content WHERE norm_ID IN ({kp}) ORDER BY cont_ID", batch
        ).fetchall():
            dst_cur.execute(
                "INSERT INTO Content VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r["cont_ID"] + offset, r["norm_ID"] + offset, r["cons_ID"] + offset,
                    r["cont_Amount"], r["cont_Type"],
                    r["cont_IsMainMaterial"], r["cont_IsCalculatePrice"],
                ),
            )
            stats["contents"] += 1
            referenced_cons.add(r["cons_ID"])

    cons_ids = list(referenced_cons)
    for i in range(0, len(cons_ids), BATCH):
        batch = cons_ids[i : i + BATCH]
        kc = ",".join("?" * len(batch))
        for r in src_conn.execute(
            f"SELECT * FROM Consumption WHERE cons_ID IN ({kc})", batch
        ).fetchall():
            dst_cur.execute(
                """INSERT INTO Consumption VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?
                )""",
                (
                    r["cons_ID"] + offset, r["kind_ID"], r["kind_Code"], r["cons_Code"],
                    r["cons_Alias"], r["cons_Name"], r["cons_Standard"],
                    r["cons_Units"], r["cons_Price"], r["cons_Market"],
                    r["cons_Supply"], r["cons_ThreeTag"], r["cons_ThreeQuotiety"],
                    r["cons_Style"], r["cons_UnitQuotiety"], r["cons_CompositeStyle"],
                    r["cons_IsCalculate"], r["cons_CalculateBasic"],
                    None, None, None,
                ),
            )
            stats["cons"] += 1

    return stats


def do_import(target_db, src_filename, offset, source_book):
    src_path = SRC_DIR / src_filename
    if not src_path.exists():
        print(f"  [SKIP] Source not found: {src_path}")
        return

    print(f"\n  {source_book} (offset={offset:,})")

    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(target_db))

    # Get root chapters
    roots = src.execute(
        "SELECT chap_ID FROM chapter WHERE chap_PID=0 OR chap_PID IS NULL"
    ).fetchall()
    root_ids = [r[0] for r in roots]

    n_chap = copy_chapter_tree(src, dst, root_ids, offset)

    all_ids = get_descendant_ids(src, root_ids)
    stats = copy_norms_data(src, dst, list(all_ids), offset, source_book)

    dst.commit()
    print(f"    chapters: {n_chap}, norms: {stats['norms']}, "
          f"contents: {stats['contents']}, consumptions: {stats['cons']}")

    src.close()
    dst.close()


def main():
    print("=" * 60)
    print("导入北京2021预算消耗量标准 → 企业定额A/C册")
    print("=" * 60)

    # Backup both target DBs
    for db_path in {A_DB, C_DB}:
        backup_db(db_path)

    for target_db, src_filename, offset, source_book in IMPORTS:
        do_import(target_db, src_filename, offset, source_book)

    # Summary
    print("\n" + "=" * 60)
    for label, db_path in [("A册", A_DB), ("C册", C_DB)]:
        conn = sqlite3.connect(str(db_path))
        n = conn.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
        c = conn.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]
        print(f"  {label}: {n} norms, {c} chapters")
        conn.close()
    print("=" * 60)
    print("全部完成")


if __name__ == "__main__":
    main()
