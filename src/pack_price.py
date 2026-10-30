# -*- coding: utf-8 -*-
"""价格包覆盖层 —— 按所选价格包给出「资源 → 单价」，供定额库浏览与导出实时覆盖写死的 cons_Price。

只读 db/resource_master.sqlite。价格事实源是 resource_price（PK res_ID+pack+price_date），
过滤一律用 pack，不用 country（那是报价来源国）。

默认包口径：status='active' 的第一个包（按 pack 字典序），与价格库、导出保持同一处定义。
"""
import sqlite3
import sys
from pathlib import Path

try:
    from config import DB_DIR
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import DB_DIR

MASTER_DB = DB_DIR / "resource_master.sqlite"

# 定额库 Consumption.cons_Style → 子目费用汇总字段
STYLE_FIELD = {3: "man", 4: "mat", 5: "mach", 6: "equip", 7: "main_mat"}

_cache = {"stamp": None, "maps": {}, "packs": None}


def _stamp():
    try:
        st = MASTER_DB.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _reset_if_stale():
    stamp = _stamp()
    if _cache["stamp"] != stamp:
        _cache["stamp"] = stamp
        _cache["maps"] = {}
        _cache["packs"] = None


def _connect():
    conn = sqlite3.connect(f"file:{MASTER_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def default_pack(conn):
    """price_api 与导出共用的默认包定义。"""
    row = conn.execute(
        "SELECT pack FROM price_pack WHERE status='active' ORDER BY pack").fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT pack FROM resource_price LIMIT 1").fetchone()
    return row[0] if row else "th_2026"


def list_packs():
    """{pack: {'currency', 'name', 'name_EN', 'status'}}，缓存至主库文件变动。"""
    _reset_if_stale()
    if _cache["packs"] is None:
        if not MASTER_DB.exists():
            return {}
        conn = _connect()
        try:
            _cache["packs"] = {
                r["pack"]: {"currency": r["currency"] or "", "name": r["name"],
                            "name_EN": r["name_EN"], "status": r["status"]}
                for r in conn.execute(
                    "SELECT pack, name, name_EN, currency, status FROM price_pack")}
            _cache["default"] = default_pack(conn)
        finally:
            conn.close()
    return _cache["packs"]


def resolve_pack(pack):
    """返回 (pack, 错误信息)。空值取默认包；未注册的包报错。"""
    packs = list_packs()
    if not packs:
        return None, "resource_master.sqlite 不存在或未注册价格包"
    if not pack:
        return _cache["default"], None
    if pack not in packs:
        return None, f"未知价格包: {pack}"
    return pack, None


def currency_of(pack):
    return list_packs().get(pack, {}).get("currency", "")


def get_price_map(pack):
    """{res_ID: price}。同一资源多个 price_date 时取最新；price 为空的不入表（视为未定价）。"""
    _reset_if_stale()
    m = _cache["maps"].get(pack)
    if m is None:
        conn = _connect()
        try:
            m = {}
            for r in conn.execute(
                    "SELECT res_ID, price FROM resource_price WHERE pack=? "
                    "ORDER BY price_date", (pack,)):
                if r["price"] is not None:
                    m[r["res_ID"]] = r["price"]
        finally:
            conn.close()
        _cache["maps"][pack] = m
    return m


def sum_norm_costs(cons_rows, price_map):
    """子目费用汇总。

    cons_rows: 可迭代，每项含 cons_Style / master_res_ID / cont_Amount。
    返回 (费用字典 {man,mat,mach,equip,main_mat}, 未定价项数)。
    缺价子项不计入汇总；无 master_res_ID 的同样算未定价。
    """
    totals = {f: 0.0 for f in STYLE_FIELD.values()}
    unpriced = 0
    for r in cons_rows:
        price = price_map.get(r["master_res_ID"]) if r["master_res_ID"] is not None else None
        if price is None:
            unpriced += 1
            continue
        field = STYLE_FIELD.get(r["cons_Style"])
        if field:
            totals[field] += (r["cont_Amount"] or 0) * price
    return totals, unpriced
