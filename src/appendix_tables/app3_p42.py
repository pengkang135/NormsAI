def render(page_data):
    css = """
    <style>
        .app3-table { border-collapse: collapse; width: 100%; font-family: "SimSun", "宋体", serif; font-size: 15px; }
        .app3-table th, .app3-table td { border: 1px solid #333; padding: 6px 8px; text-align: center; vertical-align: middle; }
        .app3-table th { background: #e8e4d8; font-weight: bold; }
        .app3-table .header-l2 { font-size: 14px; font-weight: normal; }
        .app3-table td.col-category { width: 8%; }
        .app3-table td.col-feature { width: 52%; text-align: left; padding-left: 12px; }
        .app3-table td.col-n { width: 18%; }
        .app3-table td.col-il { width: 22%; }
        .app3-table .note-row td { background: #f5f5f5; text-align: left; padding-left: 12px; font-size: 13px; color: #555; }
    </style>
    """
    html = css
    html += '<table class="app3-table">'
    html += '<thead>'
    html += '<tr><th colspan="2">土壤</th><th colspan="2">标准贯入击数</th></tr>'
    html += '<tr><th class="header-l2">类别</th><th class="header-l2">名称或特征</th><th class="header-l2">N</th><th class="header-l2">液性指数IL</th></tr>'
    html += '</thead>'
    html += '<tbody>'
    html += '<tr><td class="col-category">I</td><td class="col-feature">淤泥、淤泥混砂、软塑黏土、可塑黏土、可塑亚黏土、可塑亚砂土</td><td class="col-n">N&le;8</td><td class="col-il">IL&le;1.5</td></tr>'
    html += '<tr><td class="col-category">II</td><td class="col-feature">砂、硬塑黏土、硬塑亚黏土、硬塑亚砂土</td><td class="col-n">N&le;15</td><td class="col-il">IL&le;0.25</td></tr>'
    html += '<tr><td class="col-category">III</td><td class="col-feature">坚硬黏土、砂夹卵石、坚硬亚黏土、坚硬亚砂土</td><td class="col-n">N&le;30</td><td class="col-il">IL&le;0</td></tr>'
    html += '<tr><td class="col-category">IV</td><td class="col-feature">强风化岩、铁板砂、胶结的卵石和砾石</td><td class="col-n">N&gt;30</td><td class="col-il">&#8212;</td></tr>'
    html += '</tbody>'
    html += '<tfoot>'
    html += '<tr class="note-row"><td colspan="4">注：I、II类土壤以液性指数为主要判别标准。</td></tr>'
    html += '</tfoot>'
    html += '</table>'
    return html
