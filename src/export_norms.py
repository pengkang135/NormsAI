"""选定定额子目 → 综合单价表 Excel 导出（综合单价分析表 + 人材机价格表 两 sheet）。

列布局与 pk-norms-export 模板一致：A=序号 + B-O 14固定列 + P-BR 55消耗量列，
三级章节配色/行分组、冻结 D3、单价=人工+材料+机械、人材机费用 SUMPRODUCT 公式，
参考单价行引用「人材机价格表」单元格。

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
    ("ent_m_machine_shift", "M册 机械台班定额"),
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
CLS_LABEL = {'labour': '人工', 'materials': '材料', 'mech': '机械'}
MECH_KEYWORDS = ['机', '车', '船', '泵', '钻', '搅拌', '起重', '装载', '推土',
                 '压路', '打桩', '挖掘', '自卸', '拖轮', '驳', '发电', '空压', '电焊']

PRICE_SHEET = '人材机价格表'
ANALYSIS_SHEET = '综合单价分析表'

PRICE_HEADERS = ['编号', '类别', '名称', '项目特征', '单位', '币种', '除税单价', '税金', '含税单价',
                 '日期', '供应商', '联系人', '电话', '地址', '备注']
PRICE_COL = 7  # 除税单价所在列（G），综合单价分析表参考单价行引用此列


def classify_resource(cons_style, kind_id, cons_name):
    """人材机分类：优先 cons_Style(3/4/5/6/7)，回退 kind_ID 首位与名称关键词。"""
    if cons_style == 3:
        return 'labour'
    if cons_style in (4, 7):        # 7=未计价主材，并入材料
        return 'materials'
    if cons_style in (5, 6):        # 6=未计价设备，并入机械
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
            std_col = 'cs.cons_Standard' if _has_col(conn, 'Consumption', 'cons_Standard') else "''"
            mres_col = 'cs.master_res_ID' if _has_col(conn, 'Consumption', 'master_res_ID') else 'NULL'
            for r in conn.execute(f"""
                SELECT ct.norm_ID, cs.cons_Name, {std_col} AS cons_Standard,
                       cs.cons_Units, cs.cons_Price, {mres_col} AS master_res_ID,
                       cs.cons_Style, cs.kind_ID, cs.cons_Code, ct.cont_Amount
                FROM Content ct
                JOIN Consumption cs ON cs.cons_ID = ct.cons_ID
                WHERE ct.norm_ID IN ({ph})
                ORDER BY ct.norm_ID, cs.cons_Style, cs.kind_ID, cs.cons_Code
            """, chunk):
                # 规格已从名称拆到 cons_Standard，导出时拼回（base/spec 分开留存，供价格表列拆分）
                base = str(r['cons_Name'] or '').strip()
                spec = str(r['cons_Standard'] or '').strip()
                name = f'{base} {spec}'.strip() if spec else base
                if not name:
                    continue
                unit = str(r['cons_Units'] or '').strip()
                cons_by_norm[r['norm_ID']].append({
                    'name': name, 'base': base, 'spec': spec, 'unit': unit,
                    'price': r['cons_Price'] or 0,
                    'amount': r['cont_Amount'] or 0,
                    'master_res_id': r['master_res_ID'],
                    'cls': classify_resource(r['cons_Style'], r['kind_ID'], name),
                    'label': f"{name}\n{unit}" if unit else name,
                })
        return norm_meta, cons_by_norm
    finally:
        conn.close()


def _load_price_meta():
    """{res_ID: (price_date, source)} 当前启用价格包的定价元数据，来自 resource_master.sqlite。

    country 存的是报价来源国（派生价多为'中国'），不是价格归属，按 pack 过滤。
    """
    try:
        from config import DB_DIR
    except Exception:
        return {}
    p = DB_DIR / 'resource_master.sqlite'
    if not p.exists():
        return {}
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not _has_col(conn, 'resource_price', 'pack'):
            return {r[0]: (r[1] or '', r[2] or '') for r in conn.execute(
                "SELECT res_ID, price_date, source FROM resource_price "
                "WHERE currency='THB'")}
        row = conn.execute(
            "SELECT pack FROM price_pack WHERE status='active' ORDER BY pack").fetchone()
        pack = row[0] if row else 'th_2026'
        return {r[0]: (r[1] or '', r[2] or '') for r in conn.execute(
            "SELECT res_ID, price_date, source FROM resource_price WHERE pack=?", (pack,))}
    finally:
        conn.close()


def _load_anchor_meta():
    """{res_ID: {supplier, contact, phone, address, quote_date, project, price_excl}} 直采锚点（use_for_price=1）。"""
    try:
        from config import DB_DIR
    except Exception:
        return {}
    p = DB_DIR / 'resource_master.sqlite'
    if not p.exists():
        return {}
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not _has_col(conn, 'price_anchor', 'price_excl'):
            return {}
        out = {}
        for r in conn.execute(
            "SELECT res_ID, supplier, contact, phone, address, quote_date, project, price_excl "
            "FROM price_anchor WHERE use_for_price=1 "
            "AND (supplier != '' OR address != '' OR project != '') "
            "ORDER BY anchor_ID"):
            out.setdefault(r[0], {
                'supplier': r[1] or '', 'contact': r[2] or '', 'phone': r[3] or '',
                'address': r[4] or '', 'quote_date': r[5] or '',
                'project': r[6] or '', 'price_excl': r[7],
            })
        return out
    finally:
        conn.close()


def _build_hierarchy(norm_meta, cons_by_norm, multi_doc):
    """章 → 节 → 分项工程 → 子目（同一分项工程内定额编号去重）。

    cons_by_norm 以 (doc, norm_id) 为键；多册导出时章名加 doc_label 前缀区分。
    """
    chapters = OrderedDict()
    for meta in norm_meta.values():
        code = meta['code']
        ch_key = meta['chapter'] or '未分类'
        if multi_doc:
            ch_key = f"{meta['doc_label']} · {ch_key}"
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
            'resources': cons_by_norm.get((meta['doc'], meta['norm_id']), []),
        })
    return chapters


def _build_price_registry(all_cons):
    """所有人材机去重（按 name+unit），人→材→机排序。返回 (res_list, price_row_by_label)。"""
    by_label = OrderedDict()
    for resources in all_cons.values():
        for r in resources:
            by_label.setdefault(r['label'], r)
    res_list = sorted(by_label.values(), key=lambda x: (CLS_ORDER.get(x['cls'], 9), x['name']))
    price_row_by_label = {r['label']: i + 2 for i, r in enumerate(res_list)}
    return res_list, price_row_by_label


def _write_price_sheet(ws, res_list):
    for ci, h in enumerate(PRICE_HEADERS, 1):
        c = ws.cell(1, ci, value=h)
        c.font = FONT_HDR
        c.fill = FILL_HDR
        c.border = THIN
        c.alignment = Alignment(horizontal='center', vertical='center')
    for i, r in enumerate(res_list):
        rr = i + 2
        ws.cell(rr, 1, value=i + 1).alignment = Alignment(horizontal='center')   # 编号
        ws.cell(rr, 2, value=CLS_LABEL.get(r['cls'], ''))                        # 类别
        ws.cell(rr, 3, value=r['base'])                                          # 名称
        ws.cell(rr, 4, value=r['spec'])                                          # 项目特征
        ws.cell(rr, 5, value=r['unit'])                                          # 单位
        ws.cell(rr, 6, value='泰铢')                                             # 币种
        price = r['price']
        excl = r.get('price_excl')
        g = excl if excl is not None else price / 1.07                           # 除税单价（直采精确 / 派生 7% 推算）
        g = round(g, 4)
        c = ws.cell(rr, PRICE_COL, value=g)
        c.number_format = '#,##0.00'
        ws.cell(rr, 8, value=round(price - g, 4)).number_format = '#,##0.00'     # 税金
        ws.cell(rr, 9, value=price).number_format = '#,##0.00'                   # 含税单价
        ws.cell(rr, 10, value=r.get('quote_date') or r.get('price_date', ''))    # 日期
        sup = r.get('supplier', '') or ''
        ws.cell(rr, 11, value=sup if (sup and '?' not in sup) else r.get('project', ''))  # 供应商/项目
        ws.cell(rr, 12, value=r.get('contact', ''))                              # 联系人
        ws.cell(rr, 13, value=r.get('phone', ''))                                # 电话
        ws.cell(rr, 14, value=r.get('address', ''))                              # 地址
        note = ws.cell(rr, 15, value=r.get('source', ''))                        # 备注（定价层级+依据+项目）
        note.alignment = Alignment(wrap_text=True, vertical='top')
        for ci in range(1, len(PRICE_HEADERS) + 1):
            ws.cell(rr, ci).font = FONT_DATA
            ws.cell(rr, ci).border = THIN
    widths = {'A': 6, 'B': 8, 'C': 28, 'D': 18, 'E': 10, 'F': 8, 'G': 12, 'H': 10,
              'I': 12, 'J': 12, 'K': 16, 'L': 10, 'M': 14, 'N': 18, 'O': 60}
    for cl, w in widths.items():
        ws.column_dimensions[cl].width = w
    ws.freeze_panes = 'A2'


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


def _write_analysis_sheet(ws, chapters, warnings, price_row_by_label):
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
                def _overflow(code, n):
                    warnings.append(f"{code}：人材机 {n} 项超出 {N_CONSUMPTION} 列上限，"
                                    f"仅导出前 {N_CONSUMPTION} 项")

                blocks = _pack_blocks(sub_data['items'], _overflow)
                for bi, (resources, block_items) in enumerate(blocks):
                    block_name = sub_name if bi == 0 else f"{sub_name} ({bi + 1})"
                    row, seq = _write_block(ws, row, seq, block_name or sec_name,
                                            resources, block_items, price_row_by_label)
                    row += 1  # 分项工程间空行
            row += 1          # 节间空行
        row += 1              # 章间空行

    _finish_sheet(ws)
    return seq - 1


def _write_block(ws, row, seq, block_name, resources, items, price_row_by_label):
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

    # 参考单价行（引用人材机价格表单元格）
    price_row = row
    ws.cell(row, 3, value="参考单价 ->")
    for ri, res in enumerate(resources):
        c = ws.cell(row, QTY_COL_START + ri)
        pr = price_row_by_label.get(res['label'])
        if pr:
            c.value = f"='{PRICE_SHEET}'!${get_column_letter(PRICE_COL)}${pr}"
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


MACHINE_SHIFT_DOC = 'ent_m_machine_shift'
MACHINE_SHIFT_SHEET = '机械台班'
MACHINE_SHIFT_FALLBACK_UNIT = {
    '单价': '元/台班', '折旧费': '元', '大修费': '元', '经修费': '元',
    '安拆及场外运费费': '元', '人工费': '元', '燃料动力费': '元', '其他': '元',
    '人工': '工日', '汽油': 'L', '柴油': 'L', '电': 'kWh', '煤': 'kg', '木柴': 'kg', '水': 't',
}


def _machine_shift_cols(conn):
    import json as _json
    for (hj,) in conn.execute("SELECT header_json FROM norms_table WHERE header_json IS NOT NULL LIMIT 1"):
        try:
            h = _json.loads(hj)
        except Exception:
            continue
        return (h.get('cost_composition') or []), (h.get('consumption') or [])
    return [], []


def _write_machine_shift_sheet(wb, db_path, codes, stats, warnings):
    """机械台班定额导出：单 sheet「机械台班」，行=子目，列=8 费用组成 + 7 消耗量。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cost, usage = _machine_shift_cols(conn)
        if not cost and not usage:
            warnings.append("M册 机械台班：库中无费用/消耗表头定义")
            return
        rows = OrderedDict((c, {'name': '', 'unit': '', 'cost': {}, 'usage': {}}) for c in codes)
        unit_of = {}
        ph = ','.join(['?'] * len(codes))
        for r in conn.execute(
                "SELECT norms_code, cost_item, cost_item_unit, amount FROM norms_item "
                "WHERE norms_code IN (%s)" % ph, codes):
            code = r['norms_code']
            if code not in rows:
                continue
            item = r['cost_item'] or ''
            unit = r['cost_item_unit'] or ''
            if item and not unit_of.get(item):
                unit_of[item] = unit
            if r['amount'] is None:
                rows[code]['name'] = item
                rows[code]['unit'] = unit
            elif item in cost:
                rows[code]['cost'][item] = r['amount']
            elif item in usage:
                rows[code]['usage'][item] = r['amount']
    finally:
        conn.close()

    ws = wb.create_sheet(MACHINE_SHIFT_SHEET)
    header = ['序号', '编号', '名称', '单位']
    for c in cost:
        header.append('%s(%s)' % (c, unit_of.get(c) or MACHINE_SHIFT_FALLBACK_UNIT.get(c, '')))
    for u in usage:
        header.append('%s(%s)' % (u, unit_of.get(u) or MACHINE_SHIFT_FALLBACK_UNIT.get(u, '')))
    ws.append(header)
    for idx, code in enumerate(codes, 1):
        row = rows.get(code, {'name': '', 'unit': '', 'cost': {}, 'usage': {}})
        line = [idx, code, row['name'], row['unit'] or '台班']
        for c in cost:
            line.append(row['cost'].get(c))
        for u in usage:
            line.append(row['usage'].get(u))
        ws.append(line)
    stats['sheets'] += 1
    stats['items'] += len(codes)


def build_export_workbook(selections, db_resolver):
    """选中定额 → Workbook（人材机价格表 + 综合单价分析表 两 sheet）。

    selections: [{"doc": doc_key, "code": norm_code, "norm_id": int|None}, ...]，保持前端勾选顺序
    db_resolver: doc_key -> 数据库路径（None 表示不可用）

    返回 (Workbook, warnings, stats)
    """
    grouped = OrderedDict()
    machine_picks = []
    for sel in selections:
        doc = sel.get('doc')
        code = str(sel.get('code') or '').strip()
        if not doc or not code or doc not in EXPORT_DOC_KEYS:
            continue
        if doc == MACHINE_SHIFT_DOC:
            if code not in machine_picks:
                machine_picks.append(code)
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

    all_meta = OrderedDict()
    all_cons = {}
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

        for (code, nid), meta in norm_meta.items():
            meta['doc'] = doc
            meta['doc_label'] = label
            all_meta[(doc, code, nid)] = meta
        for norm_id, resources in cons_by_norm.items():
            all_cons[(doc, norm_id)] = resources

    price_meta = _load_price_meta()
    anchor_meta = _load_anchor_meta()
    for resources in all_cons.values():
        for r in resources:
            mid = r.get('master_res_id')
            if mid is not None and mid in price_meta:
                r['price_date'], r['source'] = price_meta[mid]
            else:
                r['price_date'] = r['source'] = ''
            if mid is not None and mid in anchor_meta:
                am = anchor_meta[mid]
                r['supplier'] = am['supplier']
                r['contact'] = am['contact']
                r['phone'] = am['phone']
                r['address'] = am['address']
                r['quote_date'] = am['quote_date']
                r['project'] = am['project']
                r['price_excl'] = am['price_excl']
                if am['project']:
                    r['source'] = r['source'] + ';project=' + am['project']
            else:
                r['supplier'] = r['contact'] = r['phone'] = r['address'] = r['quote_date'] = r['project'] = ''
                r['price_excl'] = None

    if machine_picks:
        db_path = db_resolver(MACHINE_SHIFT_DOC)
        if db_path:
            _write_machine_shift_sheet(wb, db_path, machine_picks, stats, warnings)
        else:
            warnings.append(f"M册 机械台班：数据库不可用，已跳过 {len(machine_picks)} 条")

    if grouped:
        res_list, price_row_by_label = _build_price_registry(all_cons)
        chapters = _build_hierarchy(all_meta, all_cons, len(grouped) > 1)

        ws_price = wb.create_sheet(PRICE_SHEET)
        _write_price_sheet(ws_price, res_list)
        stats['sheets'] += 1

        ws_analysis = wb.create_sheet(ANALYSIS_SHEET)
        stats['items'] += _write_analysis_sheet(ws_analysis, chapters, warnings, price_row_by_label)
        stats['sheets'] += 1

    return wb, warnings, stats
