"""
LLM-guided semantic matching: 将2021定额迁移到现有叶章节。

使用语义规则 + 层次化匹配策略:
1. 关键字硬规则 (预制≠现浇, 砌筑≠混凝土, etc.)
2. 父章节名语义匹配
3. 定额名称 → 叶章节名 diff匹配 (fallback)
"""
import sqlite3, shutil, time, re
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"

# ---- text cleaning ----
UNIT_RE = re.compile(r'\s*(m[²³23]?|kg|t|mm|cm|m|km|个|套|座|根|块|片|条|台|组|项|元|%|‰)\s*$', re.IGNORECASE)
PAREN_RE = re.compile(r'[（(][^)）]*[)）]$')
CODE_RE = re.compile(r'^[A-Za-z](\.\d+)+[\s]+')
CN_PREFIX = re.compile(r'^[一二三四五六七八九十]+[、．.\s)]*')

def clean(name):
    name = str(name or '')
    name = PAREN_RE.sub('', name)
    name = UNIT_RE.sub('', name)
    return name.strip()

def scode(name):
    m = CODE_RE.match(name)
    return name[m.end():].strip() if m else name.strip()

def strip_cn(name):
    m = CN_PREFIX.match(name)
    return name[m.end():].strip() if m else name.strip()

# ---- semantic keyword rules ----
# If a 2021 chapter name contains ANY of these keywords, it can ONLY match
# existing chapters that contain the corresponding keyword.

PREFAB_KEYWORDS = ['预制', '装配式', '装配', 'PC构件']
CAST_IN_SITU_KEYWORDS = ['现浇', '浇筑', '现场搅拌']
MASONRY_KEYWORDS = ['砖砌', '砌块', '石砌', '砖墙', '石墙', '砌体', '砖柱']
STEEL_KEYWORDS = ['钢网架', '钢屋架', '钢桁架', '钢柱', '钢梁', '钢构件', '钢板', '压型钢板', '金属结构']
WOOD_KEYWORDS = ['木屋架', '木构件', '木梁', '木柱', '木楼', '木基层']
WATERPROOF_KEYWORDS = ['防水', '防潮', '止水', '嵌缝']
INSULATION_KEYWORDS = ['保温', '隔热', '防腐', '绝热']
PIPE_KEYWORDS = ['管道', '管件', '阀门', '法兰', '给水', '排水管', '钢管', '铸铁管', '塑料管', '混凝土管']
WELL_KEYWORDS = ['检查井', '阀门井', '水表井', '雨水井', '污水井', '闸井', '跌水井', '排气井', '排泥井']
ROAD_KEYWORDS = ['路面', '路基', '基层', '面层', '沥青', '水泥混凝土路面', '路缘石', '人行道', '侧石', '平石']
BRIDGE_KEYWORDS = ['桥墩', '桥台', '梁板', '盖梁', '系梁', '承台', '墩柱', '桥面', '支座', '伸缩缝', '栏杆']
GREENING_KEYWORDS = ['种植', '绿化', '草坪', '树木', '花卉', '灌木', '乔木', '栽植', '养护']
GARDEN_KEYWORDS = ['园路', '园桥', '景石', '塑石', '假山', '水景', '喷泉', '驳岸']
LANDSCAPE_KEYWORDS = ['景观', '小品', '亭', '廊', '花架', '雕塑', '座椅']

def get_semantic_category(name):
    """Classify a chapter name into a semantic category for matching."""
    n = clean(name)
    cats = []
    if any(k in n for k in PREFAB_KEYWORDS): cats.append('prefab')
    if any(k in n for k in CAST_IN_SITU_KEYWORDS): cats.append('cast_in_situ')
    if any(k in n for k in MASONRY_KEYWORDS): cats.append('masonry')
    if any(k in n for k in STEEL_KEYWORDS): cats.append('steel')
    if any(k in n for k in WOOD_KEYWORDS): cats.append('wood')
    if any(k in n for k in WATERPROOF_KEYWORDS): cats.append('waterproof')
    if any(k in n for k in INSULATION_KEYWORDS): cats.append('insulation')
    if any(k in n for k in PIPE_KEYWORDS): cats.append('pipe')
    if any(k in n for k in WELL_KEYWORDS): cats.append('well')
    if any(k in n for k in ROAD_KEYWORDS): cats.append('road')
    if any(k in n for k in BRIDGE_KEYWORDS): cats.append('bridge')
    if any(k in n for k in GREENING_KEYWORDS): cats.append('greening')
    if any(k in n for k in GARDEN_KEYWORDS): cats.append('garden')
    if any(k in n for k in LANDSCAPE_KEYWORDS): cats.append('landscape')
    return cats

# Incompatible category pairs — cannot match across these
INCOMPATIBLE = [
    ({'prefab'}, {'cast_in_situ'}),
    ({'masonry'}, {'cast_in_situ'}),
    ({'steel'}, {'masonry'}),
    ({'wood'}, {'steel'}),
    ({'road'}, {'bridge'}),
    ({'pipe'}, {'road'}),
    ({'greening'}, {'road'}),
    ({'greening'}, {'bridge'}),
]

def is_compatible(cats_a, cats_b):
    for set_a, set_b in INCOMPATIBLE:
        if (set_a & set(cats_a)) and (set_b & set(cats_b)):
            return False
        if (set_b & set(cats_a)) and (set_a & set(cats_b)):
            return False
    return True

def match_score(a, b):
    a1, b1 = clean(a), clean(b)
    score = SequenceMatcher(None, a1, b1).ratio()
    if a1 in b1 or b1 in a1:
        score = max(score, 0.85)
    a2, b2 = strip_cn(a1), strip_cn(b1)
    if a2 != a1 or b2 != b1:
        s2 = SequenceMatcher(None, a2, b2).ratio()
        if a2 in b2 or b2 in a2:
            s2 = max(s2, 0.85)
        score = max(score, s2)
    return score

def get_leaves(conn, parent_id):
    result = []
    for cid, cname, ccode in conn.execute(
        "SELECT chap_ID, chap_Name, chap_code FROM chapter WHERE chap_PID=?", (parent_id,)
    ).fetchall():
        sub = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (cid,)).fetchone()[0]
        if sub > 0:
            result.extend(get_leaves(conn, cid))
        else:
            result.append((cid, cname, ccode))
    return result

def get_bj21_leaf_chapters(conn, parent_id):
    """Return list of (chap_id, chap_name, parent_name) for leaves with BJ21 norms."""
    result = []
    for cid, cname, ccode in conn.execute(
        "SELECT chap_ID, chap_Name, chap_code FROM chapter WHERE chap_PID=?", (parent_id,)
    ).fetchall():
        sub = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (cid,)).fetchone()[0]
        if sub > 0:
            result.extend(get_bj21_leaf_chapters(conn, cid))
        else:
            nc = conn.execute(
                "SELECT COUNT(*) FROM Norm WHERE chap_ID=? AND norm_Code LIKE 'BJ21.%'", (cid,)
            ).fetchone()[0]
            if nc > 0:
                parent_name = conn.execute(
                    "SELECT chap_Name FROM chapter WHERE chap_ID=?", (cid,)
                ).fetchone()[0]
                # get actual parent (intermediate chapter)
                p = conn.execute("SELECT chap_PID FROM chapter WHERE chap_ID=?", (cid,)).fetchone()
                pname = ''
                if p and p[0]:
                    pn = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (p[0],)).fetchone()
                    if pn: pname = pn[0]
                result.append((cid, cname, pname))
    return result

def smart_match(bj21_name, parent_name, existing_leaves, norm_index=None):
    """Semantically match a 2021 leaf chapter to best existing leaf chapter.
    Returns (best_cid, best_score)."""
    bj21_cats = get_semantic_category(bj21_name)
    # Also check parent context
    if parent_name:
        bj21_cats.extend(get_semantic_category(parent_name))

    best_cid, best_score = None, 0

    for cid, cname, _ in existing_leaves:
        existing_cats = get_semantic_category(cname)

        # Hard filter: incompatible categories cannot match
        if bj21_cats and existing_cats and not is_compatible(bj21_cats, existing_cats):
            continue

        # Chapter name match
        s = match_score(bj21_name, scode(cname))
        # Bonus for shared semantic category
        shared = set(bj21_cats) & set(existing_cats)
        if shared:
            s = min(s + 0.15 * len(shared), 1.0)

        if s > best_score:
            best_score = s
            best_cid = cid

        # Parent name match (important for empty-norm domains)
        if parent_name:
            s = match_score(parent_name, scode(cname))
            if s > best_score:
                best_score = s
                best_cid = cid

        # Combined parent + bj21 name match
        if parent_name:
            s = match_score(parent_name + " " + bj21_name, scode(cname))
            if s > best_score:
                best_score = s
                best_cid = cid

    # If no match found, relax the incompatibility filter
    if best_cid is None and bj21_cats:
        for cid, cname, _ in existing_leaves:
            s = match_score(bj21_name, scode(cname))
            if s > best_score:
                best_score = s
                best_cid = cid

    return best_cid, best_score


def process_db(db_path, domain_map, label):
    print(f"\n{'='*70}")
    print(f"{label}: LLM语义匹配")
    print(f"{'='*70}")

    bak_dir = db_path.parent / "backup"
    bak_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = bak_dir / f"{db_path.stem}.pre-llm-redist-{ts}.bak"
    shutil.copy2(db_path, bak)
    print(f"[BACKUP] {bak.name}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Build domain leaves index (dedup by existing root)
    existing_domains = {}
    for k2021, k_exist in domain_map.items():
        if k_exist not in existing_domains:
            existing_domains[k_exist] = get_leaves(conn, k_exist)

    total_existing = sum(len(v) for v in existing_domains.values())
    print(f"域内现有叶章节总数: {total_existing}")

    # Get all 2021 leaf chapters
    by_domain = defaultdict(list)
    for k2021, k_exist in domain_map.items():
        leaves = get_bj21_leaf_chapters(conn, k2021)
        by_domain[k_exist].extend([(cid, cname, pname, k2021) for cid, cname, pname in leaves])

    total_bj21_chapters = sum(len(v) for v in by_domain.values())
    total_bj21_norms = sum(
        conn.execute("SELECT COUNT(*) FROM Norm WHERE chap_ID=? AND norm_Code LIKE 'BJ21.%'", (cid,)).fetchone()[0]
        for leaves in by_domain.values() for cid, _, _, _ in leaves
    )
    print(f"2021叶章节总数: {total_bj21_chapters}, 定额总数: {total_bj21_norms}")

    # Match each 2021 leaf chapter to best existing leaf chapter
    chapter_mapping = {}  # {bj21_leaf_chap_id: (existing_leaf_chap_id, score)}
    stats = {"high": 0, "mid": 0, "low": 0, "zero": 0}

    for domain_root, bj21_chapters in by_domain.items():
        existing_leaves = existing_domains[domain_root]

        # Build norm index for this domain
        norm_index = {}
        for cid, _, _ in existing_leaves:
            norms = conn.execute("SELECT norm_Name FROM Norm WHERE chap_ID=?", (cid,)).fetchall()
            norm_index[cid] = [clean(n[0]) for n in norms]

        for bj21_cid, bj21_cname, parent_name, src_root in bj21_chapters:
            best_cid, best_score = smart_match(bj21_cname, parent_name, existing_leaves, norm_index)

            if best_cid is None and existing_leaves:
                best_cid = existing_leaves[0][0]
                best_score = 0.0

            if best_cid:
                chapter_mapping[bj21_cid] = (best_cid, best_score)
                if best_score >= 0.85: stats["high"] += 1
                elif best_score >= 0.6: stats["mid"] += 1
                elif best_score > 0: stats["low"] += 1
                else: stats["zero"] += 1

    print(f"\n匹配结果:")
    print(f"  高分(>=0.85): {stats['high']} ({100*stats['high']/max(total_bj21_chapters,1):.1f}%)")
    print(f"  中分(0.6-0.85): {stats['mid']} ({100*stats['mid']/max(total_bj21_chapters,1):.1f}%)")
    print(f"  低分(<0.6): {stats['low']} ({100*stats['low']/max(total_bj21_chapters,1):.1f}%)")
    print(f"  零分兜底: {stats['zero']}")
    print(f"  总计: {len(chapter_mapping)} / {total_bj21_chapters}")

    # Show some sample matches
    print(f"\n--- 匹配样例 (前20条) ---")
    for i, (bj21_cid, (exist_cid, score)) in enumerate(list(chapter_mapping.items())[:20]):
        bj_name = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (bj21_cid,)).fetchone()
        ex_name = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (exist_cid,)).fetchone()
        if bj_name and ex_name:
            print(f"  [{score:.2f}] '{bj_name[0]}' → '{ex_name[0]}'")

    # Check for prefab→cast-in-place misclassifications
    print(f"\n--- 预制/现浇分类检查 ---")
    prefab_misplaced = 0
    for bj21_cid, (exist_cid, score) in chapter_mapping.items():
        bj_name = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (bj21_cid,)).fetchone()
        ex_name = conn.execute("SELECT chap_Name FROM chapter WHERE chap_ID=?", (exist_cid,)).fetchone()
        if bj_name and ex_name:
            bj_cats = get_semantic_category(bj_name[0])
            ex_cats = get_semantic_category(ex_name[0])
            if 'prefab' in bj_cats and 'cast_in_situ' in ex_cats:
                print(f"  [WARN] 预制→现浇: '{bj_name[0]}' → '{ex_name[0]}'")
                prefab_misplaced += 1
    if prefab_misplaced == 0:
        print(f"  [OK] 没有预制→现浇的错配")

    # ---- Apply: update each BJ21 norm's chap_ID ----
    print(f"\n--- 迁移: 逐条更新Norm.chap_ID ---")
    by_target = defaultdict(list)
    for bj21_cid, (exist_cid, _) in chapter_mapping.items():
        norms = conn.execute(
            "SELECT norm_ID FROM Norm WHERE chap_ID=? AND norm_Code LIKE 'BJ21.%'",
            (bj21_cid,)
        ).fetchall()
        for (nid,) in norms:
            by_target[exist_cid].append(nid)

    total_updated = 0
    for exist_cid, nid_list in by_target.items():
        for i in range(0, len(nid_list), 500):
            batch = nid_list[i:i+500]
            ph = ','.join('?' * len(batch))
            n = conn.execute(
                f"UPDATE Norm SET chap_ID=? WHERE norm_ID IN ({ph})",
                [exist_cid] + batch
            ).rowcount
            total_updated += n
    conn.commit()
    print(f"共更新 {total_updated} 条Norm记录")

    # ---- Delete empty 2021 chapters ----
    print(f"\n--- 清理: 删除空章节 ---")
    deleted = 0
    while True:
        empty = conn.execute("""
            SELECT c.chap_ID FROM chapter c
            WHERE c.chap_PID != 0
            AND NOT EXISTS (SELECT 1 FROM chapter WHERE chap_PID=c.chap_ID)
            AND NOT EXISTS (SELECT 1 FROM Norm WHERE chap_ID=c.chap_ID)
        """).fetchall()
        if not empty:
            break
        for (lid,) in empty:
            conn.execute("DELETE FROM chapter WHERE chap_ID=?", (lid,))
            deleted += 1
        conn.commit()
    print(f"共删除 {deleted} 个空章节")

    # Delete empty 2021 root chapters
    for root_id in set(domain_map.keys()):
        children = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=?", (root_id,)).fetchone()[0]
        norms = conn.execute("SELECT COUNT(*) FROM Norm WHERE chap_ID=?", (root_id,)).fetchone()[0]
        if children == 0 and norms == 0:
            conn.execute("DELETE FROM chapter WHERE chap_ID=?", (root_id,))
            print(f"  删除空根章节: {root_id}")

    conn.commit()

    # ---- Verify ----
    print(f"\n--- 验证 ---")
    # Check for any BJ21 norms still in 2021 chapters
    all_2021_roots = set(domain_map.keys())
    orphan = 0
    for norm in conn.execute("SELECT norm_ID, chap_ID FROM Norm WHERE norm_Code LIKE 'BJ21.%'").fetchall():
        # Check if any ancestor is a 2021 root
        cid = norm['chap_ID']
        for _ in range(10):
            if cid in all_2021_roots:
                orphan += 1
                break
            row = conn.execute("SELECT chap_PID FROM chapter WHERE chap_ID=?", (cid,)).fetchone()
            if not row or not row[0]: break
            cid = row[0]

    total_n = conn.execute("SELECT COUNT(*) FROM Norm").fetchone()[0]
    bj12 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ12.%'").fetchone()[0]
    bj21 = conn.execute("SELECT COUNT(*) FROM Norm WHERE norm_Code LIKE 'BJ21.%'").fetchone()[0]
    roots = conn.execute("SELECT COUNT(*) FROM chapter WHERE chap_PID=0").fetchone()[0]

    print(f"残留2021子树定额: {orphan}")
    print(f"Norm总数: {total_n}, BJ12: {bj12}, BJ21: {bj21}")
    print(f"根章节数: {roots}")

    conn.close()
    print(f"\n{label} 完成!")
    return total_updated, orphan


def main():
    # ===== A册 =====
    a_db = DB_DIR / "企业定额_A册_建筑装饰.sqlite"
    A_DOMAINS = {
        # 直接映射
        131000000: 1000000,   # 土石方 → A.01
        132000000: 2000000,   # 地基处理 → A.02
        133000000: 3000000,   # 桩基 → A.03
        134000000: 6000000,   # 砌筑 → A.06
        # 135M 拆分: 混凝土及钢筋混凝土 → A.04 + A.05
        135010000: 4000000,   # 现浇混凝土构件 → A.04
        135020000: 5000000,   # 一般预制混凝土构件 → A.05
        135030000: 5000000,   # 装配式预制混凝土构件 → A.05
        135040000: 4000000,   # 钢筋及螺栓、铁件 → A.04
        # 修正: 金属结构 → A.07 (非 A.06 砌筑)
        136000000: 7000000,
        137000000: 8000000,   # 木结构 → A.08
        138000000: 13000000,  # 门窗 → A.13
        # 139M 拆分: 屋面及防水 → A.10 + A.11
        139010000: 10000000,  # 瓦、型材屋面 → A.10
        139020000: 11000000,  # 屋面防水及其他 → A.11
        139030000: 11000000,  # 墙面防水 → A.11
        139040000: 11000000,  # 楼地面防水 → A.11
        139050000: 11000000,  # 基础防水 → A.11
        139060000: 11000000,  # 防水保护层及嵌缝 → A.11
        140000000: 12000000,  # 保温隔热 → A.12
        141000000: 20000000,  # 楼地面装饰 → A.20
        # 142M 拆分: 墙柱面+幕墙 → A.21 + A.14
        142010000: 21000000,  # 墙面抹灰 → A.21
        142020000: 21000000,  # 柱梁面抹灰 → A.21
        142030000: 21000000,  # 零星抹灰 → A.21
        142040000: 21000000,  # 墙面块料面层 → A.21
        142050000: 21000000,  # 柱梁面镶贴块料 → A.21
        142060000: 21000000,  # 镶贴零星块料 → A.21
        142070000: 21000000,  # 墙饰面 → A.21
        142080000: 21000000,  # 柱梁饰面 → A.21
        142090000: 14000000,  # 幕墙工程 → A.14
        142100000: 21000000,  # 隔断 → A.21
        142110000: 21000000,  # 装配式墙面 → A.21
        143000000: 22000000,  # 天棚 → A.22
        144000000: 23000000,  # 油漆涂料 → A.23
        145000000: 24000000,  # 其他装饰 → A.24
        146000000: 33000000,  # 措施项目 → A.33
    }
    # A册已完成，跳过
    # process_db(a_db, A_DOMAINS, "A册")

    # ===== C册 =====
    c_db = DB_DIR / "企业定额_C册_市政园林.sqlite"
    C_DOMAINS = {
        # 160M (第一至三册) → 拆分到对应域
        # 170M 通用项目 → 拆分7章
        171000000: 1000000,    # 土石方 → C.01
        172000000: 1000000,    # 基底处理 → C.01
        173000000: 1000000,    # 基坑与边坡支护 → C.01
        174000000: 9000000,    # 钢筋工程 → C.09
        175000000: 1000000,    # 护坡、挡墙 → C.01
        176000000: 10000000,   # 拆除工程 → C.10
        177000000: 33000000,   # 降水、模板 → C.33
        # 180M 道路 → C.02
        180000000: 2000000,
        # 190M 桥涵 → C.03
        190000000: 3000000,
        # 230M 第四册管网 → C.05 (非 C.04 隧道!)
        231000000: 5000000,    # 砌体与装修 → C.05
        232000000: 5000000,    # 混凝土 → C.05
        233000000: 5000000,    # 给水管道 → C.05
        234000000: 5000000,    # 给水管道附属构筑物 → C.05
        235000000: 5000000,    # 排水管道 → C.05
        236000000: 5000000,    # 排水管道附属构筑物 → C.05
        # 300M 第四册下册(燃气/热力管道等) → C.05
        310000000: 5000000,
        # 370M 第五册水处理 → C.06
        380000000: 6000000,
        # 840M 园林绿化 → 拆分
        841000000: 20000000,   # 土方(绿化) → C.20
        842000000: 20000000,   # 绿化 → C.20
        843000000: 21000000,   # 园路园桥 → C.21
        844000000: 22000000,   # 园林景观 → C.22
        845000000: 33000000,   # 模板 → C.33
    }
    process_db(c_db, C_DOMAINS, "C册")


if __name__ == "__main__":
    main()
