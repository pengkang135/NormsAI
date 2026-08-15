"""企业定额库骨架建设的路径 / 常量 / 映射规则。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # -> Norms-AI/
DB_SRC = ROOT / "db"
OUTPUT_DIR = ROOT / "output"
DB_OUT = OUTPUT_DIR / "ent_norms.sqlite"
BROWSER_HTML = OUTPUT_DIR / "ent_norms_browser.html"
BROWSER_JSON = OUTPUT_DIR / "ent_norms_data.json"

WBS_XLSX = Path(
    r"f:/BaiduSyncdisk/2.清单定额/1 预算定额/5 PK定额库/"
    r"泰国数据中心项目12位WBS完整编码体系20260714_朱海.xlsx"
)

# 源库注册表（source_id 是新库内部主键）
SOURCES = {
    "BJ2012_MAIN": {
        "source_id": 1,
        "source_key": "BJ2012_MAIN",
        "source_name": "北京2012建设工程计价依据预算定额",
        "source_version": "2012",
        "db_file": "refers/北京2012_建设工程计价依据_预算定额.sqlite",
        "encoding_from": "UTF-8",
    },
    "BJ2012_REPAIR": {
        "source_id": 2,
        "source_key": "BJ2012_REPAIR",
        "source_name": "北京2012房屋修缮工程计价依据预算定额",
        "source_version": "2012",
        "db_file": "refers/北京2012_房屋修缮工程计价依据_预算定额.sqlite",
        "encoding_from": "UTF-8",
    },
    "JTS276_1": {
        "source_id": 3,
        "source_key": "JTS276_1",
        "source_name": "JTS/T 276-1-2019 沿海港口水工建筑工程定额",
        "source_version": "2019",
        "db_file": "refers/norms_jts276-1-2019_excel.sqlite",
        "encoding_from": "UTF-8",
    },
}

DISCIPLINES = ["房建", "装修", "公路市政", "机电", "园林", "水工"]

# WBS AA → discipline（朱海 20260714 版只定义 01/02，语义明确）
WBS_AA_DISCIPLINE = {
    "01": "房建",   # 土建及结构工程
    "02": "装修",   # 建筑装饰及围护工程
}

# 北京 2012 主库 chap_code 前 2 位 → 6 专业映射（按真实一级分部名称）
BJ2012_DISCIPLINE_MAP = {
    "01": "房建",       # 房屋建筑与装饰工程（装饰关键词二次拆到装修）
    "02": "园林",       # 仿古建筑工程
    "03": "机电", "04": "机电", "05": "机电", "06": "机电", "07": "机电",
    "08": "机电", "09": "机电", "10": "机电", "11": "机电", "12": "机电",
    "13": "机电", "14": "机电",
    "15": "公路市政", "16": "公路市政",
    "17": "园林",     "18": "园林",
    "19": "房建",     # 构筑物工程（水池水塔烟囱等）
    "20": "公路市政", "21": "公路市政", "22": "公路市政", "23": "公路市政",
    "24": "公路市政", "25": "公路市政", "26": "公路市政",
}

# 北京 2012 装修二次拆分关键词（chap_Name LIKE %kw%），仅在 01 分部内应用
BJ2012_DECOR_KEYWORDS = [
    "装饰", "幕墙", "涂饰", "裱糊", "油漆",
    "楼地面", "天棚", "墙面", "门窗",
]

# 北京 2012 修缮库 13 分部独立编号，需单独映射
BJ2012R_DISCIPLINE_MAP = {
    "01": "房建",       # 土建结构工程
    "02": "装修",       # 装饰装修工程
    "03": "机电", "04": "机电", "05": "机电", "06": "机电",
    "07": "机电", "08": "机电", "09": "机电", "10": "机电", "11": "机电",
    "12": "园林",       # 古建筑工程
    "13": "房建",       # 措施费分册（暂归房建）
}

JTS_DISCIPLINE = "水工"

# WBS Excel 列索引（0-based）
WBS_COL = {
    "wbs_code":     0,
    "level_label":  1,
    "aa":           2,
    "bb":           3,
    "cc":           4,
    "ddd":          5,
    "eee":          6,
    "name_cn":      7,
    "name_en":      8,
    "work_content": 9,
    "unit":        10,
    "calc_rule":   11,
    "beijing_hint":12,
}
