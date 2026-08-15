"""选定定额子目 → 综合单价表 Excel 导出。

列布局与 pk-norms-export 模板一致：A=序号 + B-O 14固定列 + P-BR 55消耗量列，
三级章节配色/行分组、冻结 D3、单价=人工+材料+机械、人材机费用 SUMPRODUCT 公式。

支持 Norm/Content/Consumption schema 的定额库（企业定额 A-E 册 + 北京定额），
章节层级由 chapter.chap_PID 递归推导，不依赖硬编码章名映射。
"""
import sqlite3
from collections import OrderedDict, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

# 可导出的 doc_key → 工作表名（≤31 字符，Excel 限制）
EXPORT_DOC_KEYS = OrderedDict([
    ("ent_a_building", "A册 建筑装饰"),
    ("ent_b_mechanical", "B册 通用安装"),
    ("ent_c_municipal", "C册 市政园林"),
    ("ent_d_water", "D册 水运工程"),
    ("ent_e_repair", "E册 房屋修缮"),
    ("bj_2012_norm", "北京2012 预算定额"),
    ("bj_2012_repair", "北京2012 房屋修缮"),
    ("bj_2021_building", "北京2021 消耗量标准"),
])

N_CONSUMPTION = 55
FIXED_COLS = 15                       # A=序号 + B-O 14 固定列
QTY_COL_START = FIXED_COLS + 1        # P
MAX_COL = FIXED_COLS + N_CONSUMPTION  # BR

EN_HEADERS = ["seq", "code", "item_name", "unit", "description", "type", "content", "rule",
              "english_name", "amount", "quantity", "rate", "labour", "materials", "mech"]
CN_HEADERS = ["序号", "定额编号", "项目名称", "单位", "项目特征", "分类指标", "工作内容", "计算规则",
              "英文名称", "成本合价", "工程量", "单价", "人工", "材料", "机械"]

FONT_NAME = '微软雅黑'
FONT_HDR = Font(name=FONT_NAME, size=9, bold=True)
FONT_HDR_EN = Font(name=FONT_NAME, size=8, bold=True)
FONT_CH = Font(name=FONT_NAME, size=9, bold=True, color='FFFFFF')
FONT_SEC = Font(name=FONT_NAME, size=9, bold=True, color='1A1A1A')
FONT_SUB = Font(name=FONT_NAME, size=9, bold=True, color='1A1A1A')
FONT_DATA = Font(name=FONT_NAME, size=9)
FONT_GRAY = Font(name=FONT_NAME, size=9, color='808080')
FONT_RES = Font(name=FONT_NAME, size=7)

FILL_HDR = PatternFill('solid', fgColor='FFD9E1F2')
FILL_CH = PatternFill('solid', fgColor='FF333F4F')
FILL_SEC = PatternFill('solid', fgColor='FFD9E1F2')
FILL_SUB = PatternFill('solid', fgColor='FFFBE5D6')

THIN = Border(left=Side('thin'), right=Side('thin'), top=Side('thin'), bottom=Side('thin'))

CLS_ORDER = {'labour': 0, 'materials': 1, 'mech': 2}
MECH_KEYWORDS = ['机', '车', '船', '泵', '钻', '搅拌', '起重', '装载', '推土',
                 '压路', '打桩', '挖掘', '自卸', '拖轮', '驳', '发电', '空压', '电焊']


def classify_resource(cons_style, kind_id, cons_name):
    """人材机分类：优先 cons_Style(3/4/5)，回退 kind_ID 首位与名称关键词。"""
    if cons_style == 3:
        return 'labour'
    if cons_style == 4:
        return 'materials'
    if cons_style == 5:
        return 'mech'
    ks = str(kind_id or 0)
    if ks.startswith('1') or '工日' in cons_name:
        return 'labour'
    if ks.startswith('3'):
        return 'mech'
    if any(kw in cons_name for kw in MECH_KEYWORDS):
        return 'mech'
    return 'materials'


def _has_col(conn, table, col):
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _chapter_paths(conn):
    """{chap_ID: [(name, name_en, code), ...]} 从根到自身的章节链。"""
    has_en = _has_col(conn, 'chapter', 'chap_Name_EN')
    en_expr = 'chap_Name_EN' if has_en else "''"
    nodes = {}
    for r in conn.execute(f"SELECT chap_ID, chap_PID, chap_Name, {en_expr}, chap_code FROM chapter"):
        nodes[r[0]] = {'pid': r[1], 'name': r[2] or '', 'en': r[3] or '', 'code': r[4] or ''}

    cache = {}

    def chain(cid):
        if cid in cache:
            return cache[cid]
        node = nodes.get(cid)
        if not node:
            return []
        cache[cid] = []  # 环保护
        pid = node['pid']
        parent = chain(pid) if pid and pid != cid and pid in nodes else []
        cache[cid] = parent + [(node['name'], node['en'], node['code'])]
        return cache[cid]

    return {cid: chain(cid) for cid in nodes}


def _split_levels(chain):
    """章节链 → (章, 章EN, 章code, 节, 分项工程)。"""
    if not chain:
        return '', '', '', '', ''
    ch_name, ch_en, ch_code = chain[0]
    sec = chain[1][0] if len(chain) > 1 else ''
    sub = chain[-1][0] if len(chain) > 2 else ''
    return ch_name, ch_en, ch_code, sec, sub


def _resolve_norm_ids(conn, picks, name_en_expr):
    """picks: [(code, norm_id|None)] → {key: Norm 行}。

    定额编号在多数库中不唯一（同编号分布在不同章节），norm_ID 为准；
    前端未提供 norm_id 时按编号取首条并沿用该 norm_ID。
    """
    by_id, by_code = {}, {}
    ids = [p[1] for p in picks if p[1] is not None]
    codes = [p[0] for p in picks if p[1] is None]

    sql_head = f"""SELECT n.norm_ID, n.norm_Code, n.norm_Name, {name_en_expr} AS name_en,
                          n.norm_Units, n.norm_BaseUnits, n.chap_ID, n.Norm_Content
                   FROM Norm n WHERE """
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        ph = ','.join(['?'] * len(chunk))
        for r in conn.execute(sql_head + f"n.norm_ID IN ({ph})", chunk):
            by_id[r['norm_ID']] = r
    for start in range(0, len(codes), 400):
        chunk = codes[start:start + 400]
        ph = ','.join(['?'] * len(chunk))
        for r in conn.execute(sql_head + f"n.norm_Code IN ({ph}) ORDER BY n.norm_ID", chunk):
            by_code.setdefault(r['norm_Code'], r)
    return by_id, by_code


def _fetch_doc_data(db_path, picks):
    """picks: [(code, norm_id|None)]，保持顺序。返回 (norm_meta, cons_by_norm)。

    norm_meta 以 (code, norm_id) 为键，与 picks 一一对应。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        name_en_expr = 'n.norm_Name_EN' if _has_col(conn, 'Norm', 'norm_Name_EN') else "''"
        paths = _chapter_paths(conn)
        by_id, by_code = _resolve_norm_ids(conn, picks, name_en_expr)

        norm_meta = OrderedDict()
        for code, nid in picks:
            r = by_id.get(nid) if nid is not None else by_code.get(code)
            if r is None:
                continue
            key = (code, nid)
            if key in norm_meta:
                continue
            ch_name, ch_en, ch_code, sec, sub = _split_levels(paths.get(r['chap_ID'], []))
            norm_meta[key] = {
                'norm_id': r['norm_ID'],
                'code': r['norm_Code'],
                'name': str(r['norm_Name'] or ''),
                'name_en': str(r['name_en'] or ''),
                'unit': str(r['norm_Units'] or r['norm_BaseUnits'] or ''),
                'content': str(r['Norm_Content'] or '').strip(),
                'chapter': ch_name, 'chapter_en': ch_en, 'chapter_code': ch_code,
                'section': sec, 'subsection': sub,
            }

        cons_by_norm = defaultdict(list)
        norm_ids = sorted({m['norm_id'] for m in norm_meta.values()})
        for start in range(0, len(norm_ids), 400):
            chunk = norm_ids[start:start + 400]
            ph = ','.join(['?'] * len(chunk))
            for r in conn.execute(f"""
                SELECT ct.norm_ID, cs.cons_Name, cs.cons_Units, cs.cons_Price,
                       cs.cons_Style, cs.kind_ID, cs.cons_Code, ct.cont_Amount
                FROM Content ct
                JOIN Consumption cs ON cs.cons_ID = ct.cons_ID
                WHERE ct.norm_ID IN ({ph})
                ORDER BY ct.norm_ID, cs.cons_Style, cs.kind_ID, cs.cons_Code
            """, chunk):
                name = str(r['cons_Name'] or '').strip()
                if not name:
                    continue
                unit = str(r['cons_Units'] or '').strip()
                cons_by_norm[r['norm_ID']].append({
                    'name': name, 'unit': unit,
                    'price': r['cons_Price'] or 0,
                    'amount': r['cont_Amount'] or 0,
                    'cls': classify_resource(r['cons_Style'], r['kind_ID'], name),
                    'label': f"{name}\n{unit}" if unit else name,
                })
        return norm_meta, cons_by_norm
    finally:
        conn.close()


def _build_hierarchy(norm_meta, cons_by_norm):
    """章 → 节 → 分项工程 → 子目（同一分项工程内定额编号去重）。"""
    chapters = OrderedDict()
    for meta in norm_meta.values():
        code = meta['code']
        ch_key = meta['chapter'] or '未分类'
        sec_key = meta['section']
        sub_key = meta['subsection']

        ch = chapters.setdefault(ch_key, {
            'en': meta['chapter_en'], 'code': meta['chapter_code'], 'sections': OrderedDict()
        })
        sec = ch['sections'].setdefault(sec_key, {'subsections': OrderedDict()})
        sub = sec['subsections'].setdefault(sub_key, {'items': []})

        if any(i['norm_id'] == meta['norm_id'] for i in sub['items']):
            continue
        sub['items'].append({
            'code': code, 'norm_id': meta['norm_id'],
            'name': meta['name'], 'name_en': meta['name_en'],
            'unit': meta['unit'], 'content': meta['content'],
            'resources': cons_by_norm.get(meta['norm_id'], []),
        })
    return chapters


def _pack_blocks(items, on_overflow):
    """把子目切成若干块，每块人材机并集 ≤ N_CONSUMPTION 列。返回 [(resources, items), ...]。

    分项工程内人材机种类超 55 列时拆成多块（各块独立资源列头与参考单价行），
    而不是截断丢弃消耗量数据。
    """
    def new_labels(item, known):
        out, seen = [], set()
        for r in item['resources']:
            if r['label'] in known or r['label'] in seen:
                continue
            seen.add(r['label'])
            out.append(r)
        return out

    blocks = []
    cur_items, cur_labels, cur_res = [], set(), []
    for item in items:
        add = new_labels(item, cur_labels)
        if cur_items and len(cur_res) + len(add) > N_CONSUMPTION:
            blocks.append((cur_res, cur_items))
            cur_items, cur_labels, cur_res = [], set(), []
            add = new_labels(item, cur_labels)
        if len(add) > N_CONSUMPTION:
            on_overflow(item['code'], len(add))
            add = add[:N_CONSUMPTION]
        cur_items.append(item)
        for r in add:
            cur_labels.add(r['label'])
            cur_res.append(r)
    if cur_items:
        blocks.append((cur_res, cur_items))

    for res, _ in blocks:
        res.sort(key=lambda x: CLS_ORDER.get(x['cls'], 9))
    return blocks


def _set_row_style(ws, row, font, fill=None):
    for ci in range(1, MAX_COL + 1):
        c = ws.cell(row, ci)
        c.font = font
        if fill:
            c.fill = fill
        c.border = THIN


def _write_headers(ws):
    for ci, h in enumerate(EN_HEADERS, 1):
        c = ws.cell(1, ci, value=h)
        c.font = FONT_HDR
        c.fill = FILL_HDR
        c.border = THIN
        c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
    for ci in range(QTY_COL_START, MAX_COL + 1):
        c = ws.cell(1, ci, value=f"qty{ci - FIXED_COLS}")
        c.font = FONT_HDR_EN
        c.fill = FILL_HDR
        c.border = THIN
    for ci, h in enumerate(CN_HEADERS, 1):
        c = ws.cell(2, ci, value=h)
        c.font = FONT_HDR
        c.fill = FILL_HDR
        c.border = THIN
        c.alignment = Alignment(wrap_text=True, horizontal='center', vertical='center')
    for ci in range(QTY_COL_START, MAX_COL + 1):
        c = ws.cell(2, ci, value=f"消耗量{ci - FIXED_COLS}")
        c.font = FONT_HDR_EN
        c.fill = FILL_HDR
        c.border = THIN


def _finish_sheet(ws):
    for cl, w in {"A": 6, "B": 12, "C": 36, "D": 10, "E": 14, "F": 14, "G": 18, "H": 16, "I": 18}.items():
        ws.column_dimensions[cl].width = w
    for ci in range(10, FIXED_COLS + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 12
    for ci in range(QTY_COL_START, MAX_COL + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 13
    ws.freeze_panes = "D3"
    ws.sheet_properties.outlinePr.summaryBelow = False


def _write_doc_sheet(ws, chapters, warnings, sheet_label):
    _write_headers(ws)
    row = 3
    seq = 1

    for ch_name, ch_data in chapters.items():
        ws.cell(row, 2, value=ch_data['code'])
        ws.cell(row, 3, value=f"【{ch_name}】")
        if ch_data['en']:
            ws.cell(row, 9, value=f"【{ch_data['en']}】")
        _set_row_style(ws, row, FONT_CH, FILL_CH)
        row += 1

        for sec_name, sec_data in ch_data['sections'].items():
            if sec_name:
                ws.cell(row, 3, value=f"《{sec_name}》")
                _set_row_style(ws, row, FONT_SEC, FILL_SEC)
                ws.row_dimensions[row].outline_level = 1
                row += 1

            for sub_name, sub_data in sec_data['subsections'].items():
                def _overflow(code, n, _label=sheet_label):
                    warnings.append(f"{_label} · {code}：人材机 {n} 项超出 {N_CONSUMPTION} 列上限，"
                                    f"仅导出前 {N_CONSUMPTION} 项")

                blocks = _pack_blocks(sub_data['items'], _overflow)
                for bi, (resources, block_items) in enumerate(blocks):
                    block_name = sub_name if bi == 0 else f"{sub_name} ({bi + 1})"
                    row, seq = _write_block(ws, row, seq, block_name or sec_name,
                                            resources, block_items)
                    row += 1  # 分项工程间空行
            row += 1          # 节间空行
        row += 1              # 章间空行

    _finish_sheet(ws)
    return seq - 1


def _write_block(ws, row, seq, block_name, resources, items):
    """写一个分项工程块：资源列头 + 参考单价行 + 数据行。返回 (下一行, 下一序号)。"""
    labour_cols, material_cols, mech_cols = [], [], []
    for ri, res in enumerate(resources):
        col = QTY_COL_START + ri
        if res['cls'] == 'labour':
            labour_cols.append(col)
        elif res['cls'] == 'materials':
            material_cols.append(col)
        else:
            mech_cols.append(col)

    # 分项工程标题 + 资源列头
    if block_name:
        ws.cell(row, 3, value=f"{{{block_name}}}")
    for ri, res in enumerate(resources):
        c = ws.cell(row, QTY_COL_START + ri, value=res['label'])
        c.alignment = Alignment(wrap_text=True, vertical='center')
    _set_row_style(ws, row, FONT_SUB, FILL_SUB)
    ws.cell(row, 3).font = FONT_SUB
    for ri in range(len(resources)):
        ws.cell(row, QTY_COL_START + ri).font = FONT_RES
    ws.row_dimensions[row].outline_level = 2
    row += 1

    # 参考单价行（预填定额基价，可覆盖）
    price_row = row
    ws.cell(row, 3, value="参考单价 ->")
    for ri, res in enumerate(resources):
        c = ws.cell(row, QTY_COL_START + ri)
        if res['price']:
            c.value = round(res['price'], 4)
        c.number_format = "#,##0.00"
    _set_row_style(ws, row, FONT_GRAY)
    ws.row_dimensions[row].outline_level = 2
    row += 1

    # 数据行
    for item in items:
        data_row = row
        ws.cell(row, 1, value=seq).number_format = "0"
        ws.cell(row, 1).alignment = Alignment(horizontal='center')
        ws.cell(row, 2, value=item['code']).number_format = "@"
        ws.cell(row, 3, value=item['name'])
        ws.cell(row, 4, value=item['unit'])
        ws.cell(row, 6, value=block_name)
        ws.cell(row, 7, value=item['content'] or "详见定额原文")
        ws.cell(row, 8, value="按设计图示尺寸计算")
        if item['name_en']:
            ws.cell(row, 9, value=item['name_en'])

        res_map = {r['label']: r['amount'] for r in item['resources']}
        for ri, res in enumerate(resources):
            val = res_map.get(res['label'])
            if val is not None:
                ws.cell(row, QTY_COL_START + ri, value=val).number_format = "#,##0.0000"

        ws.cell(row, 12, value=f"=M{data_row}+N{data_row}+O{data_row}").number_format = "#,##0.00"
        for col, cols in ((13, labour_cols), (14, material_cols), (15, mech_cols)):
            if not cols:
                continue
            pr = f"{get_column_letter(cols[0])}{price_row}:{get_column_letter(cols[-1])}{price_row}"
            qr = f"{get_column_letter(cols[0])}{data_row}:{get_column_letter(cols[-1])}{data_row}"
            ws.cell(row, col, value=f"=SUMPRODUCT({pr},{qr})").number_format = "#,##0.00"

        _set_row_style(ws, row, FONT_DATA)
        ws.row_dimensions[row].outline_level = 3
        row += 1
        seq += 1

    return row, seq


def _sheet_title(label, used):
    title = label
    for ch in '[]:*?/\\':
        title = title.replace(ch, ' ')
    title = title.strip()[:31] or 'Sheet'
    base = title
    n = 2
    while title in used:
        suffix = f" ({n})"
        title = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(title)
    return title


def build_export_workbook(selections, db_resolver):
    """选中定额 → Workbook（每册一个 sheet）。

    selections: [{"doc": doc_key, "code": norm_code, "norm_id": int|None}, ...]，保持前端勾选顺序
    db_resolver: doc_key -> 数据库路径（None 表示不可用）

    返回 (Workbook, warnings, stats)
    """
    grouped = OrderedDict()
    for sel in selections:
        doc = sel.get('doc')
        code = str(sel.get('code') or '').strip()
        if not doc or not code or doc not in EXPORT_DOC_KEYS:
            continue
        try:
            nid = int(sel['norm_id']) if sel.get('norm_id') is not None else None
        except (TypeError, ValueError):
            nid = None
        picks = grouped.setdefault(doc, [])
        if (code, nid) not in picks:
            picks.append((code, nid))

    wb = Workbook()
    wb.remove(wb.active)
    warnings = []
    stats = {'sheets': 0, 'items': 0, 'missing': []}
    used_titles = set()

    for doc, picks in grouped.items():
        label = EXPORT_DOC_KEYS[doc]
        db_path = db_resolver(doc)
        if not db_path:
            warnings.append(f"{label}：数据库不可用，已跳过 {len(picks)} 条")
            continue

        norm_meta, cons_by_norm = _fetch_doc_data(db_path, picks)
        missing = [code for code, nid in picks if (code, nid) not in norm_meta]
        if missing:
            stats['missing'].extend(missing)
            shown = ', '.join(missing[:5]) + ('…' if len(missing) > 5 else '')
            warnings.append(f"{label}：{len(missing)} 条定额在库中未找到（{shown}）")

        chapters = _build_hierarchy(norm_meta, cons_by_norm)
        if not chapters:
            continue
        ws = wb.create_sheet(_sheet_title(label, used_titles))
        stats['items'] += _write_doc_sheet(ws, chapters, warnings, label)
        stats['sheets'] += 1

    if not wb.sheetnames:
        ws = wb.create_sheet('综合单价')
        _write_headers(ws)
        _finish_sheet(ws)

    return wb, warnings, stats
