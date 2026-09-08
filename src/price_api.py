# -*- coding: utf-8 -*-
"""价格库 API —— 只读 db/resource_master.sqlite。

前端「价格库」视图的数据层：按册/专项浏览人材机价格、看溯源、看覆盖缺口。
所有端点返回 (data, status, err)，与 start.py 既有 api_* 约定一致。

口径：
- 条目以 resource 主数据为准，分册视图是 resource_usage 的子集
- 价格按 pack 过滤，不用 country（那是报价来源国）
"""
import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

try:
    from config import DB_DIR
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import DB_DIR

MASTER_DB = DB_DIR / "resource_master.sqlite"

VOL_DB = {
    "A": "企业定额_A册_建筑装饰.sqlite",
    "B": "企业定额_B册_通用安装.sqlite",
    "C": "企业定额_C册_市政园林.sqlite",
    "D": "企业定额_D册_水运工程.sqlite",
    "E": "企业定额_E册_房屋修缮.sqlite",
}

VOL_NAME = {
    "A": ("A册 建筑装饰", "Vol.A Building & Decoration"),
    "B": ("B册 通用安装", "Vol.B General Installation"),
    "C": ("C册 市政园林", "Vol.C Municipal & Landscape"),
    "D": ("D册 水运工程", "Vol.D Waterway Engineering"),
    "E": ("E册 房屋修缮", "Vol.E Building Repair"),
}

CLS_NAME = {
    3: ("人工", "Labour"),
    4: ("材料", "Material"),
    5: ("机械", "Machinery"),
    6: ("设备", "Equipment"),
    7: ("主材", "Main Material"),
}

# scope → 作用在 resource_usage 上的 WHERE 片段
SCOPE_WHERE = {
    "vol": "1=1",
    "mix": "u.kind_Code LIKE '06%'",
    "machine": "u.cons_Style = 5",
    "me_main": "u.cons_Style IN (6,7)",
    "all": "1=1",
}

MODULES = [
    ("mix", "配比材料", "Mix Materials",
     "本库只收录配比条目单价，配合比组成明细暂未入库。"),
    ("machine", "机械台班", "Machine Shifts",
     "泰国口径：租赁台月÷26 班折算，已含机上人工，不含燃料（燃料在定额中单列）。"),
    ("me_main", "机电主材", "M&E Main Materials",
     "中国定额惯例的「未计价材料」，覆盖率天然偏低，缺口条目需逐项询价补录。"),
]

TIER_NAME = {
    "T1": ("泰国直采", "Thailand direct"),
    "T2": ("邻国报价", "Neighbouring country"),
    "T3": ("中国报价", "China quote"),
    "T4": ("非洲报价", "Africa quote"),
    "S": ("近似重名", "Similar name"),
    "D": ("派生", "Derived"),
    "B": ("基准价", "Benchmark"),
}


def _conn():
    if not MASTER_DB.exists():
        return None
    conn = sqlite3.connect(f"file:{MASTER_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(cur):
    return [dict(r) for r in cur]


def _default_pack(conn):
    row = conn.execute(
        "SELECT pack FROM price_pack WHERE status='active' ORDER BY pack").fetchone()
    if row:
        return row[0]
    row = conn.execute("SELECT pack FROM resource_price LIMIT 1").fetchone()
    return row[0] if row else "th_2026"


# ── /api/price/packs ──────────────────────────────────────────────────────

def api_packs():
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        packs = []
        for r in conn.execute(
                "SELECT pack, name, name_EN, country, currency, fx_json, "
                "cutoff_date, status, note FROM price_pack ORDER BY status, pack"):
            d = dict(r)
            try:
                d["fx"] = json.loads(d.pop("fx_json") or "{}")
            except (ValueError, TypeError):
                d["fx"] = {}
            d["priced_count"] = conn.execute(
                "SELECT COUNT(*) FROM resource_price WHERE pack=?", (d["pack"],)).fetchone()[0]
            packs.append(d)
        return {"packs": packs, "default": _default_pack(conn)}, 200, None
    finally:
        conn.close()


# ── /api/price/index ──────────────────────────────────────────────────────

def api_index(pack=None):
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)
        stats = {}
        for r in conn.execute(
                "SELECT u.vol, u.cons_Style, COUNT(*) tot, "
                "       SUM(CASE WHEN p.res_ID IS NOT NULL THEN 1 ELSE 0 END) priced, "
                "       SUM(u.refs) refs "
                "FROM resource_usage u "
                "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
                "GROUP BY 1, 2", (pack,)):
            stats[(r["vol"], r["cons_Style"])] = (r["tot"], r["priced"], r["refs"] or 0)

        vols = []
        for vol in sorted(VOL_DB):
            classes = []
            tot = priced = refs = 0
            for cls in sorted(CLS_NAME):
                s = stats.get((vol, cls))
                if not s:
                    continue
                classes.append({
                    "cls": cls, "name": CLS_NAME[cls][0], "name_EN": CLS_NAME[cls][1],
                    "total": s[0], "priced": s[1], "refs": s[2],
                })
                tot, priced, refs = tot + s[0], priced + s[1], refs + s[2]
            if not classes:
                continue
            vols.append({
                "vol": vol, "name": VOL_NAME[vol][0], "name_EN": VOL_NAME[vol][1],
                "total": tot, "priced": priced, "refs": refs, "classes": classes,
            })

        modules = []
        for key, name, name_en, note in MODULES:
            r = conn.execute(
                "SELECT COUNT(DISTINCT u.res_ID) tot, "
                "       COUNT(DISTINCT CASE WHEN p.res_ID IS NOT NULL THEN u.res_ID END) priced, "
                "       SUM(u.refs) refs "
                "FROM resource_usage u "
                "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
                f"WHERE {SCOPE_WHERE[key]}", (pack,)).fetchone()
            by_vol = _rows(conn.execute(
                "SELECT u.vol, COUNT(*) tot FROM resource_usage u "
                f"WHERE {SCOPE_WHERE[key]} GROUP BY 1 ORDER BY 1"))
            modules.append({
                "key": key, "name": name, "name_EN": name_en, "note": note,
                "total": r["tot"], "priced": r["priced"], "refs": r["refs"] or 0,
                "by_vol": by_vol,
            })

        total = conn.execute(
            "SELECT COUNT(DISTINCT u.res_ID) tot, "
            "       COUNT(DISTINCT CASE WHEN p.res_ID IS NOT NULL THEN u.res_ID END) priced "
            "FROM resource_usage u "
            "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ?",
            (pack,)).fetchone()

        return {
            "pack": pack, "vols": vols, "modules": modules,
            "total": total["tot"], "priced": total["priced"],
        }, 200, None
    finally:
        conn.close()


# ── /api/price/list ───────────────────────────────────────────────────────

def build_list_query(pack, scope="all", vol=None, cls=None, priced=None, tier=None, q=None):
    """筛选条件 → (base_sql, args)。列表与 Excel 导出共用，保证导出的就是屏幕上那一批。"""
    where = [SCOPE_WHERE[scope]]
    args = [pack]

    if vol:
        where.append("u.vol = ?")
        args.append(vol)
    if cls:
        where.append("u.cons_Style = ?")
        args.append(int(cls))
    if priced == "yes":
        where.append("p.res_ID IS NOT NULL")
    elif priced == "no":
        where.append("p.res_ID IS NULL")
    if tier:
        tiers = [x.strip() for x in tier.split(",") if x.strip()]
        if tiers:
            where.append("p.tier IN (%s)" % ",".join("?" * len(tiers)))
            args.extend(tiers)
    if q:
        kw = f"%{q.strip()}%"
        where.append("(r.res_Name LIKE ? OR r.res_Standard LIKE ? OR "
                     "r.res_Name_EN LIKE ? OR r.res_Code LIKE ? OR u.cons_Name LIKE ?)")
        args.extend([kw] * 5)

    base = (
        "FROM resource_usage u "
        "JOIN resource r ON r.res_ID = u.res_ID "
        "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
        "WHERE " + " AND ".join(where))
    return base, args


def api_list(pack=None, scope="all", vol=None, cls=None, priced=None,
             tier=None, q=None, limit=200, offset=0):
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)
        if scope not in SCOPE_WHERE:
            return None, 400, f"未知 scope: {scope}"

        base, args = build_list_query(pack, scope, vol, cls, priced, tier, q)

        # 有价数必须是筛选条件下的全量，不能让 LIMIT 分页把覆盖率算小
        agg = conn.execute(
            "SELECT COUNT(DISTINCT u.res_ID), "
            "       COUNT(DISTINCT CASE WHEN p.res_ID IS NOT NULL THEN u.res_ID END), "
            "       SUM(u.refs) "
            f"{base}", args).fetchone()
        total, total_priced, total_refs = agg[0], agg[1], agg[2] or 0

        sql = (
            "SELECT u.res_ID, r.res_Code, r.res_Class, r.res_Class_Name, r.res_Family, "
            "       r.res_Name, r.res_Standard, r.res_Unit, "
            "       r.res_Name_EN, r.res_Standard_EN, r.res_Unit_EN, r.res_Status, "
            "       p.price, p.currency, p.price_date, p.tier, p.price_kind, "
            "       p.price_excl, p.price_incl, "
            "       SUM(u.refs) AS refs, "
            "       GROUP_CONCAT(DISTINCT u.vol) AS vols, "
            "       MIN(u.cons_Style) AS cons_Style, "
            "       MIN(u.kind_Code) AS kind_Code "
            f"{base} "
            "GROUP BY u.res_ID "
            "ORDER BY (p.price IS NULL) DESC, refs DESC, r.res_Code "
            "LIMIT ? OFFSET ?")
        items = _rows(conn.execute(sql, args + [int(limit), int(offset)]))
        for it in items:
            it["vols"] = sorted((it.get("vols") or "").split(",")) if it.get("vols") else []

        return {
            "pack": pack, "scope": scope, "vol": vol, "cls": cls,
            "total": total, "priced": total_priced, "refs": total_refs,
            "limit": int(limit), "offset": int(offset),
            "items": items,
        }, 200, None
    finally:
        conn.close()


# ── /api/price/detail ─────────────────────────────────────────────────────

def api_detail(res_id, pack=None):
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)
        res = conn.execute(
            "SELECT * FROM resource WHERE res_ID = ?", (res_id,)).fetchone()
        if not res:
            return None, 404, f"资源不存在: {res_id}"

        price = conn.execute(
            "SELECT * FROM resource_price WHERE res_ID = ? AND pack = ? "
            "ORDER BY price_date DESC LIMIT 1", (res_id, pack)).fetchone()

        quotes = _rows(conn.execute(
            "SELECT q.*, m.match_type, m.confidence, m.xfactor "
            "FROM quote_match m JOIN price_quote q ON q.quote_ID = m.quote_ID "
            "WHERE m.res_ID = ? "
            "ORDER BY m.confidence DESC, q.quote_date DESC LIMIT 60", (res_id,)))

        usage = {(r["vol"], r["cons_ID"]): r["refs"]
                 for r in conn.execute(
                     "SELECT vol, cons_ID, refs FROM resource_usage WHERE res_ID = ?",
                     (res_id,))}
        aliases = []
        for r in conn.execute(
                "SELECT src_vol, src_cons_ID, src_Name, src_Standard, src_Unit, "
                "       src_Price, unit_factor, match_type, confidence "
                "FROM resource_alias WHERE res_ID = ? ORDER BY src_vol", (res_id,)):
            key = (r["src_vol"], r["src_cons_ID"])
            if key not in usage:
                continue  # 去重前的历史别名，不展示
            d = dict(r)
            d["refs"] = usage[key]
            aliases.append(d)

        norms = _norms_using(res_id, sorted({v for v, _ in usage}))

        anchor = _rows(conn.execute(
            "SELECT thb_price, use_for_price, source, supplier, contact, phone, "
            "       address, quote_date, project, price_excl, price_incl "
            "FROM price_anchor WHERE res_ID = ?", (res_id,)))

        return {
            "pack": pack,
            "resource": dict(res),
            "price": dict(price) if price else None,
            "quotes": quotes,
            "aliases": aliases,
            "norms": norms,
            "anchors": anchor,
        }, 200, None
    finally:
        conn.close()


# ── /api/price/benchmark ───────────────────────────────────────────────────

def api_benchmark_detail(res_id, pack=None):
    """基准价明细：资源 + 加权中位数结论 + benchmark_obs 观测明细。"""
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)
        res = conn.execute(
            "SELECT * FROM resource WHERE res_ID = ?", (res_id,)).fetchone()
        if not res:
            return None, 404, f"资源不存在: {res_id}"

        price = conn.execute(
            "SELECT * FROM resource_price WHERE res_ID = ? AND pack = ? "
            "AND price_kind = 'benchmark' ORDER BY price_date DESC LIMIT 1",
            (res_id, pack)).fetchone()

        obs = _rows(conn.execute(
            "SELECT obs_type, obs_ref, value_cny, weight, n_raw, source "
            "FROM benchmark_obs WHERE res_ID = ? AND pack = ? "
            "ORDER BY weight DESC, value_cny", (res_id, pack)))

        return {
            "pack": pack,
            "resource": dict(res),
            "price": dict(price) if price else None,
            "observations": obs,
        }, 200, None
    finally:
        conn.close()


def _norms_using(res_id, vols, limit_per_vol=30):
    """引用该资源的定额子目，按册查各自的库。"""
    out = []
    for vol in vols:
        path = DB_DIR / VOL_DB.get(vol, "")
        if not path.exists():
            continue
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        try:
            for r in c.execute(
                    "SELECT n.norm_Code, n.norm_Name, n.norm_Name_EN, n.norm_Units, "
                    "       ct.cont_Amount, cs.cons_Units "
                    "FROM Consumption cs "
                    "JOIN Content ct ON ct.cons_ID = cs.cons_ID "
                    "JOIN Norm n ON n.norm_ID = ct.norm_ID "
                    "WHERE cs.master_res_ID = ? "
                    "ORDER BY ct.cont_Amount DESC LIMIT ?", (res_id, limit_per_vol)):
                d = dict(r)
                d["vol"] = vol
                out.append(d)
        except sqlite3.Error:
            pass
        finally:
            c.close()
    return out


# ── /api/price/coverage ───────────────────────────────────────────────────

def api_coverage(pack=None, gap_limit=60):
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)

        matrix = _rows(conn.execute(
            "SELECT u.vol, u.cons_Style AS cls, COUNT(*) total, "
            "       SUM(CASE WHEN p.res_ID IS NOT NULL THEN 1 ELSE 0 END) priced, "
            "       SUM(u.refs) refs, "
            "       SUM(CASE WHEN p.res_ID IS NOT NULL THEN u.refs ELSE 0 END) refs_priced "
            "FROM resource_usage u "
            "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
            "GROUP BY 1, 2 ORDER BY 1, 2", (pack,)))
        for m in matrix:
            m["cls_name"] = CLS_NAME.get(m["cls"], ("", ""))[0]
            m["cls_name_EN"] = CLS_NAME.get(m["cls"], ("", ""))[1]
            m["vol_name"] = VOL_NAME.get(m["vol"], ("", ""))[0]

        tiers = _rows(conn.execute(
            "SELECT tier, price_kind, COUNT(*) n FROM resource_price "
            "WHERE pack = ? GROUP BY 1, 2 ORDER BY n DESC", (pack,)))
        for t in tiers:
            t["tier_name"] = TIER_NAME.get(t["tier"], ("", ""))[0]
            t["tier_name_EN"] = TIER_NAME.get(t["tier"], ("", ""))[1]

        gaps = _rows(conn.execute(
            "SELECT u.res_ID, r.res_Code, r.res_Class_Name, r.res_Name, r.res_Standard, "
            "       r.res_Unit, r.res_Name_EN, r.res_Unit_EN, "
            "       SUM(u.refs) refs, GROUP_CONCAT(DISTINCT u.vol) vols "
            "FROM resource_usage u "
            "JOIN resource r ON r.res_ID = u.res_ID "
            "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
            "WHERE p.res_ID IS NULL "
            "GROUP BY u.res_ID ORDER BY refs DESC LIMIT ?", (pack, int(gap_limit))))
        for g in gaps:
            g["vols"] = sorted((g.get("vols") or "").split(",")) if g.get("vols") else []

        summary = conn.execute(
            "SELECT COUNT(DISTINCT u.res_ID) total, "
            "       COUNT(DISTINCT CASE WHEN p.res_ID IS NOT NULL THEN u.res_ID END) priced, "
            "       SUM(u.refs) refs, "
            "       SUM(CASE WHEN p.res_ID IS NOT NULL THEN u.refs ELSE 0 END) refs_priced "
            "FROM resource_usage u "
            "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ?",
            (pack,)).fetchone()

        return {
            "pack": pack, "summary": dict(summary),
            "matrix": matrix, "tiers": tiers, "gaps": gaps,
        }, 200, None
    finally:
        conn.close()


# ── /api/price/gap ────────────────────────────────────────────────────────

_QUOTE_POOL = {}


def _norm_chars(s):
    """取中文字符 + 英数 token，用于粗粒度名称相似度。"""
    if not s:
        return set()
    s = re.sub(r"[\s\(\)（）\[\]【】,，、/\\·\-—_+]", "", s)
    return set(s)


def _quote_pool(conn, specialty_like):
    key = specialty_like
    if key in _QUOTE_POOL:
        return _QUOTE_POOL[key]
    rows = _rows(conn.execute(
        "SELECT quote_ID, name, name_en, features, unit, std_unit, unit_factor, "
        "       country, currency, price_incl, price_excl, tax, quote_date, "
        "       supplier, contact, phone, address, source_doc, specialty, tier "
        "FROM price_quote WHERE specialty LIKE ?", (specialty_like,)))
    for r in rows:
        text = (r["name"] or "") + (r["features"] or "")
        r["_text"] = re.sub(r"\s+", "", text)
        r["_chars"] = _norm_chars(text)
    _QUOTE_POOL[key] = rows
    return rows


def _prefilter(a, b):
    """字符集粗筛：Jaccard 与包含度取大，用于快速缩小候选池。"""
    if not a or not b:
        return 0.0
    inter = a & b
    if len(inter) < 2:
        return 0.0
    return max(len(inter) / len(a | b), len(inter) / min(len(a), len(b)) * 0.7)


def _rerank(target_text, cand_text, same_unit):
    """序列相似度重排：顺序敏感，比字符集更能区分「不锈钢塔」与「不锈钢地漏」。"""
    ratio = SequenceMatcher(None, target_text, cand_text).ratio()
    return round(min(1.0, ratio + (0.08 if same_unit else 0.0)), 3)


def api_gap(pack=None, vol=None, cls=None, scope="me_main",
            specialty="%", limit=40, cand=6, min_score=0.34):
    """缺口清单 + 候选报价撮合（只读，不写回）。

    两段式匹配：字符集粗筛取 top40 → SequenceMatcher 顺序敏感重排 → 阈值截断。
    宁可返回空候选，也不塞噪声——这是人工询价的入口，假阳性比缺项更贵。

    默认搜全部 13,421 条报价，不按 specialty 预筛：该列标注不可靠
    （`机电设备` 里混着 UPVC 排水管与履带挖掘机）。传 specialty 可手动收窄。
    """
    conn = _conn()
    if not conn:
        return None, 500, "resource_master.sqlite 不存在"
    try:
        pack = pack or _default_pack(conn)
        if scope not in SCOPE_WHERE:
            return None, 400, f"未知 scope: {scope}"

        where = [SCOPE_WHERE[scope], "p.res_ID IS NULL"]
        args = [pack]
        if vol:
            where.append("u.vol = ?")
            args.append(vol)
        if cls:
            where.append("u.cons_Style = ?")
            args.append(int(cls))

        base = ("FROM resource_usage u "
                "JOIN resource r ON r.res_ID = u.res_ID "
                "LEFT JOIN resource_price p ON p.res_ID = u.res_ID AND p.pack = ? "
                "WHERE " + " AND ".join(where))
        # 撮合每条约 16ms，全量跑不现实，但截了多少必须报出来
        total_gaps = conn.execute(
            f"SELECT COUNT(DISTINCT u.res_ID) {base}", args).fetchone()[0]

        items = _rows(conn.execute(
            "SELECT u.res_ID, r.res_Code, r.res_Class_Name, r.res_Name, r.res_Standard, "
            "       r.res_Unit, r.res_Name_EN, r.res_Standard_EN, r.res_Unit_EN, "
            "       SUM(u.refs) refs, GROUP_CONCAT(DISTINCT u.vol) vols "
            f"{base} GROUP BY u.res_ID ORDER BY refs DESC LIMIT ?", args + [int(limit)]))

        pool = _quote_pool(conn, specialty)
        for it in items:
            it["vols"] = sorted((it.get("vols") or "").split(",")) if it.get("vols") else []
            raw = (it["res_Name"] or "") + (it["res_Standard"] or "")
            target_text = re.sub(r"\s+", "", raw)
            target_chars = _norm_chars(raw)
            unit = (it["res_Unit"] or "").strip()

            rough = []
            for qr in pool:
                s = _prefilter(target_chars, qr["_chars"])
                if s > 0:
                    rough.append((s, qr))
            rough.sort(key=lambda x: -x[0])

            scored = []
            for _, qr in rough[:40]:
                same_unit = bool(unit) and unit == (qr["std_unit"] or qr["unit"] or "").strip()
                s = _rerank(target_text, qr["_text"], same_unit)
                if s >= min_score:
                    scored.append((s, same_unit, qr))
            scored.sort(key=lambda x: (-x[0], not x[1]))

            # 名称相似但单位不符是最常见的假阳性（接地编织铜线 m ↔ 编织袋 个），
            # 单独标出来让人一眼看到，不靠分数掩盖。
            it["candidates"] = [
                {**{k: v for k, v in qr.items() if not k.startswith("_")},
                 "score": s, "unit_match": same_unit}
                for s, same_unit, qr in scored[:int(cand)]]

        return {
            "pack": pack, "scope": scope, "vol": vol, "cls": cls,
            "specialty": specialty, "pool_size": len(pool), "min_score": min_score,
            "count": len(items), "total": total_gaps,
            "truncated": max(0, total_gaps - len(items)),
            "matched": sum(1 for it in items if it["candidates"]),
            "items": items,
        }, 200, None
    finally:
        conn.close()
