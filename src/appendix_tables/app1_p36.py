import re

CAT_Y_SPLIT = 5
CAT_PRE_GAP = 12
CAT_CONT_GAP = 15


def _col(x):
    if x < 65:
        return 0
    if x < 225:
        return 1
    if x < 295:
        return 2
    if x < 440:
        return 3
    return 4


def _build_groups(lines):
    groups = []
    for l in sorted(lines, key=lambda x: x['y']):
        if l['y'] < 242:
            continue
        matched = False
        for g in groups:
            if abs(l['y'] - g['y0']) <= CAT_Y_SPLIT:
                g['items'].append(l)
                matched = True
                break
        if not matched:
            groups.append({'y0': l['y'], 'items': [l]})
    return groups


def _parse_group(g):
    vals = [''] * 5
    cat = ''
    for item in sorted(g['items'], key=lambda x: x['x']):
        c = _col(item['x'])
        t = item['text'].strip()
        if c == 0:
            m = re.match(r'^[Ⅰ-Ⅳ]+', t)
            if m:
                cat = m.group()
        vals[c] = (vals[c] + t) if vals[c] else t
    return vals, cat


def render(page_data):
    lines = page_data.get('lines', [])
    table_lines = [l for l in lines if 193 <= l['y'] <= 355]
    if not table_lines:
        return '<p style="color:#999;padding:20px;">No table data found on this page.</p>'

    table_lines.sort(key=lambda l: (l['y'], l['x']))

    title_raw = ''
    for l in table_lines:
        if l['y'] < 210:
            title_raw = l['text'].strip()
            break
    title = re.sub(r'\s{2,}', '  ', title_raw)

    groups = _build_groups(table_lines)
    parsed = []
    cat_indices = []
    for i, g in enumerate(groups):
        vals, cat = _parse_group(g)
        parsed.append({'y': g['y0'], 'vals': vals, 'cat': cat})
        if cat:
            cat_indices.append(i)

    for i, e in enumerate(parsed):
        if e['cat']:
            continue
        prev_ci = max((ci for ci in cat_indices if ci < i), default=None)
        next_ci = min((ci for ci in cat_indices if ci > i), default=None)

        prev_gap = e['y'] - parsed[prev_ci]['y'] if prev_ci is not None else float('inf')
        next_gap = parsed[next_ci]['y'] - e['y'] if next_ci is not None else float('inf')
        has_method = bool(e['vals'][4])

        if prev_ci is not None and (prev_gap < CAT_CONT_GAP or has_method):
            e['_belongs'] = prev_ci
        elif next_ci is not None and next_gap < CAT_PRE_GAP:
            e['_belongs'] = next_ci
            e['_pre'] = True
        else:
            e['_belongs'] = prev_ci if prev_ci is not None else next_ci

    categories = []
    for ci in cat_indices:
        cat_entry = {
            'cat': parsed[ci]['cat'],
            'vals': list(parsed[ci]['vals']),
            'subs': []
        }
        categories.append(cat_entry)

    ci_to_idx = {ci: idx for idx, ci in enumerate(cat_indices)}

    for i, e in enumerate(parsed):
        if e['cat']:
            continue
        cat_idx = ci_to_idx.get(e['_belongs'])
        if cat_idx is None:
            continue
        cur = categories[cat_idx]
        v = e['vals']

        if e.get('_pre'):
            for c in range(5):
                if v[c]:
                    cur['vals'][c] = v[c] + cur['vals'][c] if cur['vals'][c] else v[c]
        else:
            has_soil = bool(v[1])
            if has_soil and cur['vals'][1]:
                if bool(v[4]):
                    cur['subs'].append(list(v))
                else:
                    for c in range(5):
                        if v[c]:
                            cur['vals'][c] = cur['vals'][c] + v[c] if cur['vals'][c] else v[c]
            else:
                for c in range(5):
                    if v[c]:
                        cur['vals'][c] = cur['vals'][c] + v[c] if cur['vals'][c] else v[c]

    for cat in categories:
        for vals_list in [cat['vals']] + cat['subs']:
            if vals_list[1].startswith('黏土、干燥黄土、干淤泥、含少'):
                vals_list[1] = '黏土、干燥黄土、干淤泥、含少量砾石黏土'

    rows = []
    for cat in categories:
        rows.append(cat['vals'])
        for sr in cat['subs']:
            rows.append(sr)

    html = []
    html.append('<style>')
    html.append(
        '.app1-table{border-collapse:collapse;width:100%;font-family:"Microsoft YaHei","SimSun",sans-serif;font-size:13px;margin:12px 0;}'
    )
    html.append(
        '.app1-table th{border:1px solid #888;padding:6px 8px;text-align:center;background:#e8e4d8;font-weight:bold;vertical-align:middle;}'
    )
    html.append(
        '.app1-table td{border:1px solid #888;padding:6px 8px;vertical-align:middle;line-height:1.6;}'
    )
    html.append('.app1-table .cat{text-align:center;font-weight:bold;white-space:nowrap;}')
    html.append('.app1-table .col-soil{min-width:150px;}')
    html.append('.app1-table .col-density{text-align:center;white-space:nowrap;min-width:90px;}')
    html.append('.app1-table .col-feature{min-width:140px;}')
    html.append('.app1-table .col-method{min-width:130px;}')
    html.append(
        '.app1-title{font-size:14px;font-weight:bold;text-align:center;margin:8px 0 6px;font-family:"Microsoft YaHei","SimSun",sans-serif;}'
    )
    html.append('</style>')

    if title:
        html.append(f'<div class="app1-title">{title}</div>')

    html.append('<table class="app1-table">')
    html.append('<thead><tr>')
    html.append('<th>土壤类别</th>')
    html.append('<th>土质名称</th>')
    html.append('<th>自然湿容重<br>(kg/m³)</th>')
    html.append('<th>外形特征</th>')
    html.append('<th>开挖方式</th>')
    html.append('</tr></thead>')
    html.append('<tbody>')

    i = 0
    total = len(rows)
    while i < total:
        vals = rows[i]
        is_cat_row = bool(vals[0])

        sub_count = 0
        j = i + 1
        while j < total and not rows[j][0]:
            sub_count += 1
            j += 1

        html.append('<tr>')

        cat_display = vals[0] if is_cat_row else ''
        if sub_count > 0:
            html.append(f'<td class="cat" rowspan="{sub_count + 1}">{cat_display}</td>')
        else:
            html.append(f'<td class="cat">{cat_display}</td>')

        html.append(f'<td class="col-soil">{vals[1]}</td>')

        if sub_count > 0:
            html.append(f'<td class="col-density" rowspan="{sub_count + 1}">{vals[2]}</td>')
            html.append(f'<td class="col-feature" rowspan="{sub_count + 1}">{vals[3]}</td>')
        else:
            html.append(f'<td class="col-density">{vals[2]}</td>')
            html.append(f'<td class="col-feature">{vals[3]}</td>')

        html.append(f'<td class="col-method">{vals[4]}</td>')
        html.append('</tr>')

        for k in range(i + 1, j):
            svals = rows[k]
            html.append('<tr>')
            html.append(f'<td class="col-soil">{svals[1]}</td>')
            html.append(f'<td class="col-method">{svals[4]}</td>')
            html.append('</tr>')

        i = j

    html.append('</tbody></table>')
    return '\n'.join(html)
