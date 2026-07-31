from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "output"
OCR_DIR = OUTPUT_DIR / "ocr"
MD_DIR = OUTPUT_DIR / "intermediate" / "md"
PLAN_DIR = ROOT_DIR / "plan"

# 数据库目录（所有定额 SQLite 均存放于此）
DB_DIR = ROOT_DIR / "db"

# 主定额数据库（多来源统一入口）
JTS_2004_DB_PATH = DB_DIR / "《沿海港口水工建筑工程定额》(交水发[2004]247号).sqlite"
JTS_2019_DB_PATH = DB_DIR / "JTS_T_276-1-2019_沿海港口水工建筑工程定额.sqlite"
JTS_2019_EXCEL_DB_PATH = DB_DIR / "norms_jts276-1-2019_excel.sqlite"
JTS_2019_EXCEL_REF_DB_PATH = DB_DIR / "norms_jts276-3-2019_excel.sqlite"

BJ_2012_NORM_DB_PATH = DB_DIR / "北京2012_建设工程计价依据_预算定额.sqlite"
BJ_2012_REPAIR_DB_PATH = DB_DIR / "北京2012_房屋修缮工程计价依据_预算定额.sqlite"
BJ_2012_BILL_2013_DB_PATH = DB_DIR / "北京2012_建设工程计价依据_清单规范2013.sqlite"
BJ_2012_BILL_2009_DB_PATH = DB_DIR / "北京2012_建设工程计价依据_清单规范2009.sqlite"

# 向后兼容别名
DB_PATH = JTS_2004_DB_PATH
STAGING_DB_PATH = DB_DIR / "staging.sqlite"
FINAL_DB_PATH = DB_DIR / "final.sqlite"

PDF_PATH = Path(r"F:\BaiduSyncdisk\5.报价\2026-5 Laldia\5 报价书\4 定额\《沿海港口水工建筑工程定额》(交水发[2004]247号.pdf")

DEFAULT_PAGE_RANGE = range(1, 513)
GOLD_SET_PAGES = (29, 33, 35, 40, 45, 50, 58, 60)

OCR_RENDER_SCALE = 2.0
OCR_CONFIDENCE_THRESHOLD = 0.30
OCR_MULTI_PASS = (
    {"scale": 2.0, "contrast": 1.0, "label": "base"},
    {"scale": 3.0, "contrast": 1.0, "label": "hires"},
    {"scale": 2.0, "contrast": 1.5, "label": "contrast"},
)

TABLE_KEYWORDS = ("定额编号", "顺序号", "项目", "单位", "基价", "人工")
COST_KEYWORDS = ("人工", "材料", "机械", "船机", "基价", "合计")
GENERIC_HEADER_TOKENS = {
    "定额编号",
    "顺序号",
    "项目",
    "单位",
    "土壤类别",
    "类别",
    "厚度",
    "运距",
    "工程内容",
}

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    doc_number TEXT,
    publisher TEXT,
    effective_date TEXT,
    total_pages INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES chapter(id),
    sort_order INTEGER NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    subtitle TEXT,
    toc_page INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    is_appendix INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS section_text (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id),
    page INTEGER NOT NULL,
    seq_no INTEGER NOT NULL,
    type TEXT,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appendix_table (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER REFERENCES chapter(id),
    table_name TEXT NOT NULL,
    page_from INTEGER,
    page_to INTEGER,
    is_continued INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS appendix_row (
    id INTEGER PRIMARY KEY,
    table_id INTEGER NOT NULL REFERENCES appendix_table(id),
    page INTEGER NOT NULL,
    sort_order INTEGER NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS norms_table (
    id INTEGER PRIMARY KEY,
    chapter_id INTEGER REFERENCES chapter(id),
    section_title TEXT,
    subsection_title TEXT,
    work_content TEXT,
    unit TEXT,
    page INTEGER NOT NULL,
    seq_on_page INTEGER DEFAULT 1,
    header_json TEXT NOT NULL,
    row_count INTEGER,
    col_count INTEGER
);

CREATE TABLE IF NOT EXISTS norms_item (
    id INTEGER PRIMARY KEY,
    table_id INTEGER NOT NULL REFERENCES norms_table(id),
    page INTEGER NOT NULL,
    norms_code TEXT NOT NULL,
    sort_order INTEGER,
    attr_level1 TEXT,
    attr_level2 TEXT,
    attr_level3 TEXT,
    attr_level4 TEXT,
    attr1_label TEXT,
    attr2_label TEXT,
    attr3_label TEXT,
    attr4_label TEXT,
    cost_item TEXT NOT NULL,
    cost_item_unit TEXT,
    amount REAL,
    ocr_source TEXT DEFAULT 'OCR',
    data_quality TEXT DEFAULT 'raw'
);

CREATE TABLE IF NOT EXISTS page_index (
    page INTEGER PRIMARY KEY,
    page_type TEXT NOT NULL,
    chapter_id INTEGER REFERENCES chapter(id),
    table_id INTEGER REFERENCES norms_table(id),
    appendix_id INTEGER REFERENCES appendix_table(id),
    text_preview TEXT,
    ocr_status TEXT DEFAULT 'pending',
    ocr_lines INTEGER,
    ocr_confidence REAL
);

CREATE TABLE IF NOT EXISTS ocr_block (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page INTEGER NOT NULL,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    text TEXT NOT NULL,
    confidence REAL,
    block_type TEXT,
    render_scale REAL DEFAULT 2.0,
    pass_label TEXT DEFAULT 'standard'
);

CREATE INDEX IF NOT EXISTS idx_norms_code ON norms_item(norms_code);
CREATE INDEX IF NOT EXISTS idx_norms_table ON norms_item(table_id);
CREATE INDEX IF NOT EXISTS idx_page_type ON page_index(page_type);
CREATE INDEX IF NOT EXISTS idx_ocr_page ON ocr_block(page);
"""