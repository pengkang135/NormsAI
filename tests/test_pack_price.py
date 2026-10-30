# -*- coding: utf-8 -*-
"""价格包覆盖层：单价与子目汇总按所选国别重算。基于真实 db/，只读。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import start  # noqa: E402
from src import pack_price  # noqa: E402

pytestmark = pytest.mark.skipif(not pack_price.MASTER_DB.exists(), reason="缺少 resource_master.sqlite")

PACKS = ["th_2026", "cn_2026", "lk_2026"]
DOC = "ent_b_mechanical"


@pytest.fixture(scope="module")
def chap_id():
    conn = start.get_db(DOC)
    cid = conn.execute("SELECT chap_ID FROM Norm WHERE norm_MainMaterialPrice > 0 LIMIT 1").fetchone()[0]
    conn.close()
    return cid


def test_resolve_pack_default_and_unknown():
    pack, err = pack_price.resolve_pack(None)
    assert err is None and pack == "th_2026"
    assert pack_price.resolve_pack("th_2026") == ("th_2026", None)
    pack, err = pack_price.resolve_pack("zz")
    assert pack is None and "未知价格包" in err


def test_currency_of():
    assert [pack_price.currency_of(p) for p in PACKS] == ["THB", "CNY", "USD"]


def test_price_map_matches_table():
    import sqlite3
    conn = sqlite3.connect(f"file:{pack_price.MASTER_DB}?mode=ro", uri=True)
    n = conn.execute("SELECT COUNT(*) FROM resource_price WHERE pack='cn_2026' AND price IS NOT NULL").fetchone()[0]
    conn.close()
    assert len(pack_price.get_price_map("cn_2026")) == n


def test_sum_norm_costs_skips_unpriced():
    rows = [
        {"cons_Style": 3, "master_res_ID": 1, "cont_Amount": 2},
        {"cons_Style": 4, "master_res_ID": 2, "cont_Amount": 3},
        {"cons_Style": 5, "master_res_ID": 3, "cont_Amount": 1},   # 缺价
        {"cons_Style": 7, "master_res_ID": None, "cont_Amount": 1},  # 无主数据链接
    ]
    totals, unpriced = pack_price.sum_norm_costs(rows, {1: 10.0, 2: 5.0})
    assert totals["man"] == 20.0 and totals["mat"] == 15.0
    assert totals["mach"] == 0.0 and totals["main_mat"] == 0.0
    assert unpriced == 2


@pytest.mark.parametrize("pack", PACKS)
def test_items_follow_pack(chap_id, pack):
    items, status, err = start.api_items(DOC, chap_id, pack)
    assert err is None and status == 200
    price_map = pack_price.get_price_map(pack)
    conn = start.get_db(DOC)
    by_name = {}
    for r in conn.execute("SELECT cons_Name, master_res_ID FROM Consumption"):
        by_name.setdefault(r["cons_Name"], set()).add(r["master_res_ID"])
    conn.close()
    checked = 0
    for it in items:
        if "unit_price" not in it:
            continue
        rids = by_name[it["cost_item"].split(" ")[0]] if it["cost_item"].split(" ")[0] in by_name else None
        if it.get("unpriced"):
            assert it["unit_price"] is None
        else:
            checked += 1
            assert it["unit_price"] is not None
            if rids:
                assert any(abs(it["unit_price"] - round(price_map[r], 4)) < 1e-3 for r in rids if r in price_map)
    assert checked > 0


@pytest.mark.parametrize("pack", PACKS)
def test_norm_amount_is_sum_of_priced_subitems(chap_id, pack):
    items, _, _ = start.api_items(DOC, chap_id, pack)
    by_code = {}
    for it in items:
        by_code.setdefault(it["norms_code"], []).append(it)
    verified = 0
    for code, rows in by_code.items():
        name_rows = [r for r in rows if "unpriced_count" in r]
        if not name_rows:
            continue
        name = name_rows[0]
        subs = [r for r in rows if r.get("attr_level3") in ("人工", "材料", "机械")]
        expect = sum((r["amount"] or 0) * r["unit_price"] for r in subs if r["unit_price"] is not None)
        assert abs(name["amount"] - expect) < max(0.05, expect * 1e-3), code
        verified += 1
    assert verified > 0


def test_packs_produce_different_prices(chap_id):
    amounts = {}
    for pack in PACKS:
        items, _, _ = start.api_items(DOC, chap_id, pack)
        amounts[pack] = items[0]["amount"]
    assert len(set(amounts.values())) == 3


def test_default_equals_default_pack(chap_id):
    a, _, _ = start.api_items(DOC, chap_id, None)
    b, _, _ = start.api_items(DOC, chap_id, "th_2026")
    assert a == b


def test_non_linked_library_unchanged():
    conn = start.get_db("bj_2012_norm")
    cid = conn.execute("SELECT chap_ID FROM Norm LIMIT 1").fetchone()[0]
    conn.close()
    a, _, _ = start.api_items("bj_2012_norm", cid, "th_2026")
    b, _, _ = start.api_items("bj_2012_norm", cid, "cn_2026")
    assert a == b
    assert not any("unpriced_count" in it for it in a)


def test_export_follows_pack(chap_id):
    from config import DB_DIR
    from src.export_norms import build_export_workbook
    conn = start.get_db(DOC)
    sel = [{"doc": DOC, "code": r[0], "norm_id": r[1]} for r in
           conn.execute("SELECT norm_Code, norm_ID FROM Norm WHERE chap_ID=? LIMIT 3", (chap_id,))]
    conn.close()
    resolver = lambda k: DB_DIR / start.DOC_TO_DB[k]
    seen = {}
    for pack, cur_zh in [("th_2026", "泰铢"), ("cn_2026", "人民币"), ("lk_2026", "美元")]:
        wb, warnings, stats = build_export_workbook(sel, resolver, pack)
        ws = wb["人材机价格表"]
        assert stats["pack"] == pack
        assert ws.cell(2, 6).value == cur_zh
        seen[pack] = ws.cell(2, 9).value
    assert len(set(seen.values())) == 3
    with pytest.raises(ValueError):
        build_export_workbook(sel, resolver, "zz")
