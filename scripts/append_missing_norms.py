"""
追加缺失的定额子目到C册，并创建E册（房屋修缮）。

C册追加：
  - ch02 仿古建筑工程 (1,427条)
  - ch20-26 城市轨道交通工程 (3,507条)
E册（新建）：
  - 北京2012修缮库全部 (13,552条)

ID冲突处理：源ID + OFFSET 避免与目标库既有ID重叠。
"""
import sqlite3
import shutil
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
BJ_MAIN = DB_DIR / "refers" / "北京2012_建设工程计价依据_预算定额.sqlite"
BJ_REPAIR = DB_DIR / "refers" / "北京2012_房屋修缮工程计价依据_预算定额.sqlite"
C_DB = DB_DIR / "企业定额_C册_市政园林.sqlite"
E_DB = DB_DIR / "企业定额_E册_房屋修缮.sqlite"

OFFSET_CH02 = 100000
OFFSET_CH20 = 200000
OFFSET_E = 500000


def backup_db(db_path: Path):
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir(exist_ok=True)
    bak = backup_dir / f"{db_path.stem}.pre-append-{int(time.time())}.bak"
    shutil.copy2(db_path, bak)
    print(f"[BACKUP] {bak.name}")


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
    """Copy chapter hierarchy. Src 6 cols → dst 8 cols (+chap_Name_EN, +chap_Content_EN)."""
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


def copy_norms_data(src_conn, dst_conn, chap_ids, offset, source_lib, source_book):
    """Copy Norm/Content/Consumption. Handles column count differences:
    Src Norm=23 cols, Dst Norm=25 (+2 EN cols)
    Src Consumption=18 cols, Dst Consumption=21 (+3 EN cols)
    Content=7 cols both.
    """
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
            """INSERT INTO norm_source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_norm_id, source_lib, r["norm_ID"], r["norm_Code"],
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


def append_chapters_to_c(src_conn, dst_conn, root_codes, offset, source_book):
    """Append BJ chapters identified by root_codes to C册."""
    rows = src_conn.execute(
        f"SELECT chap_ID FROM chapter WHERE chap_code IN ({','.join('?'*len(root_codes))})",
        list(root_codes),
    ).fetchall()
    root_ids = [r[0] for r in rows]
    all_ids = get_descendant_ids(src_conn, root_ids)

    n_chap = copy_chapter_tree(src_conn, dst_conn, root_ids, offset)

    leaf_ids = list(all_ids)
    stats = copy_norms_data(
        src_conn, dst_conn, leaf_ids, offset,
        "北京2012_建设工程计价依据_预算定额", source_book,
    )
    return n_chap, stats


def append_to_c():
    print("=" * 60)
    print("C册追加: ch02 仿古建筑 + ch20-26 城市轨道交通")
    print("=" * 60)

    backup_db(C_DB)

    src = sqlite3.connect(str(BJ_MAIN))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(C_DB))

    # ch02 仿古建筑
    n_chap, stats = append_chapters_to_c(
        src, dst, ["02"], OFFSET_CH02, "仿古建筑工程"
    )
    print(f"  ch02 仿古建筑: {n_chap} chapters, {stats['norms']} norms, "
          f"{stats['contents']} contents, {stats['cons']} consumptions")

    # ch20-26 城市轨道交通
    n_chap2, stats2 = append_chapters_to_c(
        src, dst, ["20", "21", "22", "23", "24", "25", "26"],
        OFFSET_CH20, "城市轨道交通工程"
    )
    print(f"  ch20-26 城市轨道: {n_chap2} chapters, {stats2['norms']} norms, "
          f"{stats2['contents']} contents, {stats2['cons']} consumptions")

    dst.commit()

    total_n = dst.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    total_c = dst.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]
    print(f"\n  C册最终: {total_n} norms, {total_c} chapters")

    src.close()
    dst.close()


def create_e():
    """Create E册 (房屋修缮) from 北京2012 修缮库."""
    print("\n" + "=" * 60)
    print("E册新建: 北京2012 房屋修缮工程计价依据")
    print("=" * 60)

    if E_DB.exists():
        backup_dir = DB_DIR / "backup"
        backup_dir.mkdir(exist_ok=True)
        bak = backup_dir / f"{E_DB.stem}.pre-recreate-{int(time.time())}.bak"
        shutil.copy2(E_DB, bak)
        print(f"[BACKUP] {bak.name}")
        E_DB.unlink()

    src = sqlite3.connect(str(BJ_REPAIR))
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(E_DB))

    dst.executescript("""
        CREATE TABLE division (
            code TEXT PRIMARY KEY, name TEXT, name_EN TEXT,
            description TEXT, description_EN TEXT
        );
        CREATE TABLE sub_division (
            division_code TEXT, sub_code TEXT, name TEXT, name_EN TEXT,
            PRIMARY KEY (division_code, sub_code)
        );
        CREATE TABLE enterprise_item (
            code TEXT PRIMARY KEY, division TEXT, sub_level3 TEXT,
            name TEXT, unit TEXT, item_feature TEXT,
            calc_rule TEXT, work_content TEXT, gb_ref TEXT, chap_ID INTEGER
        );
        CREATE TABLE chapter (
            chap_ID INTEGER PRIMARY KEY, chap_PID INTEGER NOT NULL,
            chap_Name TEXT, chap_Content TEXT, chap_code TEXT,
            chap_Index TEXT, chap_Name_EN TEXT, chap_Content_EN TEXT
        );
        CREATE TABLE Norm (
            norm_ID INTEGER PRIMARY KEY, chap_ID INTEGER NOT NULL,
            chap_Code TEXT, norm_SortID INTEGER, norm_Specialty TEXT,
            norm_Code TEXT, norm_Name TEXT, norm_Units TEXT,
            norm_BaseUnits TEXT, norm_UnitsQuotiety REAL,
            norm_ManPrice REAL, norm_MaterialPrice REAL, norm_MachinePrice REAL,
            norm_OtherPrice REAL, norm_MainMaterialPrice REAL, norm_EquipmentPrice REAL,
            norm_AttachTag1 TEXT, norm_AttachTag INTEGER, norm_isEntity TEXT,
            norm_Tag INTEGER, norm_direct TEXT, norm_Alias TEXT, Norm_Content INT,
            norm_Name_EN TEXT, Norm_Content_EN TEXT
        );
        CREATE TABLE Consumption (
            cons_ID INTEGER PRIMARY KEY, kind_ID INTEGER, kind_Code TEXT,
            cons_Code TEXT, cons_Alias TEXT, cons_Name TEXT, cons_Standard TEXT,
            cons_Units TEXT, cons_Price DECIMAL, cons_Market DECIMAL,
            cons_Supply REAL, cons_ThreeTag TEXT, cons_ThreeQuotiety REAL,
            cons_Style INTEGER, cons_UnitQuotiety INTEGER, cons_CompositeStyle INTEGER,
            cons_IsCalculate TEXT, cons_CalculateBasic TEXT,
            cons_Name_EN TEXT, cons_Standard_EN TEXT, cons_Units_EN TEXT
        );
        CREATE TABLE Content (
            cont_ID INTEGER PRIMARY KEY, norm_ID INTEGER NOT NULL,
            cons_ID INTEGER NOT NULL, cont_Amount REAL, cont_Type INTEGER,
            cont_IsMainMaterial TEXT, cont_IsCalculatePrice TEXT
        );
        CREATE TABLE norm_source (
            norm_ID INTEGER PRIMARY KEY, source_lib TEXT NOT NULL,
            source_norm_id INTEGER, source_norm_code TEXT,
            source_chap_id INTEGER, source_chap_name TEXT,
            source_chap_path TEXT, source_book TEXT, import_time TEXT
        );
        CREATE TABLE nrm_item (
            code TEXT, name TEXT, level_one TEXT, level_two TEXT,
            nrm_section_title TEXT, name_ZH TEXT
        );
        CREATE INDEX idx_norm_chap ON Norm(chap_ID);
        CREATE INDEX idx_content_norm ON Content(norm_ID);
        CREATE INDEX idx_content_cons ON Content(cons_ID);
        CREATE INDEX idx_norm_source_lib ON norm_source(source_lib);
    """)

    # Copy chapter tree
    roots = src.execute(
        "SELECT chap_ID FROM chapter WHERE chap_PID=0 OR chap_PID IS NULL"
    ).fetchall()
    root_ids = [r[0] for r in roots]
    all_ids = get_descendant_ids(src, root_ids)

    placeholders = ",".join("?" * len(all_ids))
    chapters = src.execute(
        f"SELECT * FROM chapter WHERE chap_ID IN ({placeholders}) ORDER BY chap_ID",
        list(all_ids),
    ).fetchall()
    for r in chapters:
        new_id = r["chap_ID"] + OFFSET_E
        new_pid = r["chap_PID"] + OFFSET_E if r["chap_PID"] and r["chap_PID"] != 0 else 0
        dst.execute(
            "INSERT INTO chapter VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id, new_pid, r["chap_Name"], r["chap_Content"],
                r["chap_code"], r["chap_Index"], None, None,
            ),
        )
    print(f"  chapters: {len(chapters)}")

    # Create division entries from top-level chapters
    top_chapters = src.execute(
        "SELECT * FROM chapter WHERE chap_PID=0 OR chap_PID IS NULL ORDER BY chap_code"
    ).fetchall()
    for r in top_chapters:
        dst.execute(
            "INSERT INTO division VALUES (?, ?, ?, ?, ?)",
            (f"E.{r['chap_code']}", r["chap_Name"], None, r["chap_Content"] or "", None),
        )

    # Copy Norm/Consumption/Content
    leaf_ids = list(all_ids)
    stats = copy_norms_data(
        src, dst, leaf_ids, OFFSET_E,
        "北京2012_房屋修缮工程计价依据_预算定额", "房屋修缮工程",
    )
    print(f"  Norm: {stats['norms']}, Content: {stats['contents']}, Consumption: {stats['cons']}")

    dst.commit()

    total_n = dst.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    total_c = dst.execute("SELECT COUNT(*) FROM chapter").fetchone()[0]
    print(f"\n  E册最终: {total_n} norms, {total_c} chapters")
    print(f"[DONE] {E_DB}")

    src.close()
    dst.close()


def main():
    append_to_c()
    create_e()
    print("\n" + "=" * 60)
    print("全部完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
