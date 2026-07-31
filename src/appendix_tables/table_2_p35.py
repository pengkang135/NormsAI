def render(page_data):
    css = """
    <style>
        .tab2-wrap { max-width: 680px; margin: 0 auto; font-family: "Microsoft YaHei", "SimSun", sans-serif; font-size: 13px; color: #333; }
        .tab2-title { text-align: center; font-weight: bold; font-size: 14px; padding: 6px 0 10px; }
        .tab2 { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .tab2 th, .tab2 td { border: 1px solid #aaa; padding: 5px 6px; text-align: center; vertical-align: middle; }
        .tab2 thead th { background: #e8e4d8; font-weight: bold; }
        .tab2 .group-label { background: #ddd9cc; font-weight: bold; width: 80px; }
        .tab2 .col-wth { width: 72px; }
        .tab2 .col-depth { width: 90px; }
        .tab2 td { background: #fff; }
    </style>
    """

    html = css
    html += '<div class="tab2-wrap">\n'
    html += '<div class="tab2-title">表2 石方工程放坡系数参考表</div>\n'
    html += '<table class="tab2">\n'

    html += '<thead>\n'
    html += '<tr>\n'
    html += '<th class="col-wth" rowspan="2">岩石类别</th>\n'
    html += '<th class="col-wth" rowspan="2">风化程度</th>\n'
    html += '<th colspan="4">开 挖 深 度（h）</th>\n'
    html += '</tr>\n'
    html += '<tr>\n'
    html += '<th class="col-depth">h&le;4m</th>\n'
    html += '<th class="col-depth">4m&lt;h&le;8m</th>\n'
    html += '<th class="col-depth">8m&lt;h&le;12m</th>\n'
    html += '<th class="col-depth">12m&lt;h&le;15m</th>\n'
    html += '</tr>\n'
    html += '</thead>\n'

    html += '<tbody>\n'

    rows = [
        ("硬质岩石", "微风化",           "1:0.10", "1:0.20", "1:0.30", "1:0.35", True,  3),
        ("",         "中等风化<br>(X∼XIII 级)", "1:0.20", "1:0.35", "1:0.45", "1:0.50", False, 0),
        ("",         "强风化",           "1:0.35", "1:0.50", "1:0.65", "1:0.75", False, 0),
        ("软质岩石", "微风化",           "1:0.35", "1:0.50", "1:0.65", "1:0.75", True,  3),
        ("",         "中等风化<br>(V∼IX 级)",   "1:0.50", "1:0.75", "1:0.90", "1:1.00", False, 0),
        ("",         "强风化",           "1:0.75", "1:1.00", "1:1.15", "1:1.25", False, 0),
    ]

    for rock, weather, v1, v2, v3, v4, is_group, rowspan in rows:
        html += '<tr>\n'
        if is_group:
            html += f'<td class="group-label" rowspan="{rowspan}">{rock}</td>\n'
        if weather:
            html += f'<td>{weather}</td>\n'
            html += f'<td>{v1}</td>\n'
            html += f'<td>{v2}</td>\n'
            html += f'<td>{v3}</td>\n'
            html += f'<td>{v4}</td>\n'
        html += '</tr>\n'

    html += '</tbody>\n'
    html += '</table>\n'
    html += '</div>\n'

    return html
