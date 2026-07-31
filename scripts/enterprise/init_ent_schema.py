"""建骨架空库（幂等）：CREATE TABLE IF NOT EXISTS + 视图。

用法：
    python -m scripts.enterprise.init_ent_schema         # 幂等建表
    python -m scripts.enterprise.init_ent_schema --drop  # 删库重建
"""
from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path
import sys

# 允许 python scripts/enterprise/init_ent_schema.py 直接跑
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.enterprise.config_ent import DB_OUT, SOURCES, DISCIPLINES

# ==================== DDL ====================
DDL = """
-- 1. 源库登记
CREATE TABLE IF NOT EXISTS source_registry (
    source_id      INTEGER PRIMARY KEY,
    source_key     TEXT UNIQUE NOT NULL,
    source_name    TEXT NOT NULL,
    source_version TEXT,
    db_file        TEXT,
    encoding_from  TEXT DEFAULT 'UTF-8',
    row_stats_json TEXT,
    imported_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    note           TEXT
);

-- 2. WBS 骨架
CREATE TABLE IF NOT EXISTS wbs_class (
    wbs_code       TEXT PRIMARY KEY CHECK(length(wbs_code)=12),
    parent_code    TEXT,
    level          INTEGER NOT NULL CHECK(level BETWEEN 1 AND 5),
    aa             TEXT NOT NULL,
    bb             TEXT,
    cc             TEXT,
    ddd            TEXT,
    eee            TEXT,
    name_cn        TEXT NOT NULL,
    name_en        TEXT,
    work_content   TEXT,
    standard_unit  TEXT,
    calc_rule      TEXT,
    beijing_hint   TEXT,
    discipline     TEXT,
    extension_flag INTEGER DEFAULT 0,
    source_row     INTEGER,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(parent_code) REFERENCES wbs_class(wbs_code)
);
CREATE INDEX IF NOT EXISTS ix_wbs_parent     ON wbs_class(parent_code);
CREATE INDEX IF NOT EXISTS ix_wbs_discipline ON wbs_class(discipline);
CREATE INDEX IF NOT EXISTS ix_wbs_aa_bb_cc   ON wbs_class(aa, bb, cc);
CREATE INDEX IF NOT EXISTS ix_wbs_level      ON wbs_class(level);

-- 3. 北京 2012 主库 & 修缮库共用一组 src_bj2012_* 表（复合主键 source_id）
CREATE TABLE IF NOT EXISTS src_bj2012_chapter (
    source_id     INTEGER NOT NULL,
    chap_ID       INTEGER NOT NULL,
    chap_PID      INTEGER,
    chap_Name     TEXT,
    chap_Content  TEXT,
    chap_code     TEXT,   -- 注意原库小写
    chap_Index    TEXT,
    discipline    TEXT,
    PRIMARY KEY (source_id, chap_ID)
);
CREATE INDEX IF NOT EXISTS ix_bj_chap_pid  ON src_bj2012_chapter(source_id, chap_PID);
CREATE INDEX IF NOT EXISTS ix_bj_chap_code ON src_bj2012_chapter(source_id, chap_code);

CREATE TABLE IF NOT EXISTS src_bj2012_norm (
    source_id             INTEGER NOT NULL,
    norm_ID               INTEGER NOT NULL,
    chap_ID               INTEGER,
    chap_Code             TEXT,   -- 注意原库大写
    norm_SortID           INTEGER,
    norm_Specialty        TEXT,
    norm_Code             TEXT,   -- source_code：定额编号如 '1-1'
    norm_Name             TEXT,
    norm_Units            TEXT,
    norm_BaseUnits        TEXT,
    norm_UnitsQuotiety    REAL,
    norm_ManPrice         REAL,
    norm_MaterialPrice    REAL,
    norm_MachinePrice     REAL,
    norm_OtherPrice       REAL,
    norm_MainMaterialPrice REAL,
    norm_EquipmentPrice   REAL,
    norm_AttachTag1       TEXT,
    norm_AttachTag        TEXT,
    norm_isEntity         TEXT,
    norm_Tag              INTEGER,
    norm_direct           REAL,
    norm_Alias            TEXT,
    Norm_Content          TEXT,
    discipline            TEXT,
    PRIMARY KEY (source_id, norm_ID)
);
CREATE INDEX IF NOT EXISTS ix_bj_norm_chap ON src_bj2012_norm(source_id, chap_ID);
CREATE INDEX IF NOT EXISTS ix_bj_norm_code ON src_bj2012_norm(source_id, norm_Code);
CREATE INDEX IF NOT EXISTS ix_bj_norm_disc ON src_bj2012_norm(discipline);

CREATE TABLE IF NOT EXISTS src_bj2012_consumption (
    source_id             INTEGER NOT NULL,
    cons_ID               INTEGER NOT NULL,
    kind_ID               INTEGER,
    kind_Code             TEXT,
    cons_Code             TEXT,
    cons_Alias            TEXT,
    cons_Name             TEXT,
    cons_Standard         TEXT,
    cons_Units            TEXT,
    cons_Price            REAL,
    cons_Market           REAL,
    cons_Supply           REAL,
    cons_ThreeTag         INTEGER,
    cons_ThreeQuotiety    REAL,
    cons_Style            INTEGER,
    cons_UnitQuotiety     INTEGER,
    cons_CompositeStyle   INTEGER,
    cons_IsCalculate      TEXT,
    cons_CalculateBasic   TEXT,
    PRIMARY KEY (source_id, cons_ID)
);
CREATE INDEX IF NOT EXISTS ix_bj_cons_code ON src_bj2012_consumption(source_id, cons_Code);

CREATE TABLE IF NOT EXISTS src_bj2012_content (
    source_id            INTEGER NOT NULL,
    cont_ID              INTEGER NOT NULL,
    norm_ID              INTEGER,
    cons_ID              INTEGER,
    cont_Amount          REAL,
    cont_Type            INTEGER,
    cont_IsMainMaterial  INTEGER,
    cont_IsCalculatePrice INTEGER,
    PRIMARY KEY (source_id, cont_ID)
);
CREATE INDEX IF NOT EXISTS ix_bj_content_norm ON src_bj2012_content(source_id, norm_ID);
CREATE INDEX IF NOT EXISTS ix_bj_content_cons ON src_bj2012_content(source_id, cons_ID);

-- 4. JTS 港口水工（Norms-AI 六表 schema，只搬 3 张有数据的）
CREATE TABLE IF NOT EXISTS src_jts276_chapter (
    source_id    INTEGER NOT NULL,
    id           INTEGER NOT NULL,
    parent_id    INTEGER,
    sort_order   INTEGER,
    level        INTEGER,
    title        TEXT,
    subtitle     TEXT,
    toc_page     INTEGER,
    start_page   INTEGER,
    end_page     INTEGER,
    is_appendix  INTEGER,
    PRIMARY KEY (source_id, id)
);

CREATE TABLE IF NOT EXISTS src_jts276_norms_table (
    source_id        INTEGER NOT NULL,
    id               INTEGER NOT NULL,
    chapter_id       INTEGER,
    section_title    TEXT,
    subsection_title TEXT,
    work_content     TEXT,
    unit             TEXT,
    page             INTEGER,
    seq_on_page      INTEGER,
    header_json      TEXT,
    row_count        INTEGER,
    col_count        INTEGER,
    PRIMARY KEY (source_id, id)
);

CREATE TABLE IF NOT EXISTS src_jts276_norms_item (
    source_id      INTEGER NOT NULL,
    id             INTEGER NOT NULL,
    table_id       INTEGER,
    page           INTEGER,
    norms_code     TEXT,     -- source_code
    sort_order     INTEGER,
    attr_level1    TEXT,
    attr_level2    TEXT,
    attr_level3    TEXT,
    attr_level4    TEXT,
    attr1_label    TEXT,
    attr2_label    TEXT,
    attr3_label    TEXT,
    attr4_label    TEXT,
    cost_item      TEXT,
    cost_item_unit TEXT,
    amount         REAL,
    ocr_source     TEXT,
    data_quality   TEXT,
    PRIMARY KEY (source_id, id)
);
CREATE INDEX IF NOT EXISTS ix_jts_item_code  ON src_jts276_norms_item(source_id, norms_code);
CREATE INDEX IF NOT EXISTS ix_jts_item_table ON src_jts276_norms_item(source_id, table_id);

-- 5. WBS ↔ 源定额桥接表（本次留空）
CREATE TABLE IF NOT EXISTS wbs_norm_mapping (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    wbs_code     TEXT NOT NULL,
    source_id    INTEGER NOT NULL,
    src_table    TEXT NOT NULL,     -- 'bj2012_norm' | 'jts276_norms_item'
    src_row_id   INTEGER NOT NULL,
    source_code  TEXT,               -- 冗余 norm_Code / norms_code
    priority     INTEGER DEFAULT 1,
    match_type   TEXT,                -- 'manual' | 'ai' | 'rule' | 'seed'
    confidence   REAL,
    note         TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    created_by   TEXT,
    FOREIGN KEY(wbs_code)  REFERENCES wbs_class(wbs_code),
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id),
    UNIQUE(wbs_code, source_id, src_table, src_row_id)
);
CREATE INDEX IF NOT EXISTS ix_map_wbs ON wbs_norm_mapping(wbs_code);
CREATE INDEX IF NOT EXISTS ix_map_src ON wbs_norm_mapping(source_id, src_table, src_row_id);
"""

# 6 个专业视图（表达 WBS 骨架 + 已映射定额）
VIEWS_SQL_TEMPLATE = """
DROP VIEW IF EXISTS "vw_disc_{d}";
CREATE VIEW "vw_disc_{d}" AS
SELECT
    w.wbs_code, w.parent_code, w.level, w.name_cn, w.name_en,
    w.standard_unit, w.beijing_hint, w.discipline,
    m.source_id, m.src_table, m.src_row_id, m.source_code, m.priority, m.confidence
FROM wbs_class w
LEFT JOIN wbs_norm_mapping m ON m.wbs_code = w.wbs_code
WHERE w.discipline = '{d}';
"""

DROP_ALL_SQL = """
DROP VIEW  IF EXISTS "vw_disc_房建";
DROP VIEW  IF EXISTS "vw_disc_装修";
DROP VIEW  IF EXISTS "vw_disc_公路市政";
DROP VIEW  IF EXISTS "vw_disc_机电";
DROP VIEW  IF EXISTS "vw_disc_园林";
DROP VIEW  IF EXISTS "vw_disc_水工";
DROP TABLE IF EXISTS wbs_norm_mapping;
DROP TABLE IF EXISTS src_jts276_norms_item;
DROP TABLE IF EXISTS src_jts276_norms_table;
DROP TABLE IF EXISTS src_jts276_chapter;
DROP TABLE IF EXISTS src_bj2012_content;
DROP TABLE IF EXISTS src_bj2012_consumption;
DROP TABLE IF EXISTS src_bj2012_norm;
DROP TABLE IF EXISTS src_bj2012_chapter;
DROP TABLE IF EXISTS wbs_class;
DROP TABLE IF EXISTS source_registry;
"""


def init_schema(db_path: Path, drop: bool = False) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if drop:
            conn.executescript(DROP_ALL_SQL)
        conn.executescript(DDL)
        for d in DISCIPLINES:
            conn.executescript(VIEWS_SQL_TEMPLATE.format(d=d))

        # source_registry 初始 3 行（幂等 INSERT OR IGNORE）
        for _, s in SOURCES.items():
            conn.execute(
                """INSERT OR IGNORE INTO source_registry
                       (source_id, source_key, source_name, source_version, db_file, encoding_from)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (s["source_id"], s["source_key"], s["source_name"],
                 s["source_version"], s["db_file"], s["encoding_from"]),
            )
        conn.commit()

        stats = {
            "tables": conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0],
            "views": conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='view'"
            ).fetchone()[0],
            "indexes": conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0],
            "source_registry_rows": conn.execute(
                "SELECT COUNT(*) FROM source_registry"
            ).fetchone()[0],
        }
        return stats
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="删库重建")
    args = ap.parse_args()
    stats = init_schema(DB_OUT, drop=args.drop)
    print(f"[ok] ent_norms.sqlite -> {DB_OUT}")
    for k, v in stats.items():
        print(f"     {k}: {v}")


if __name__ == "__main__":
    main()
