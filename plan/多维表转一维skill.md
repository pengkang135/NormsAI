# Skill: 定额表通用转换器

## 1. 问题背景
定额类表格（如挖掘机挖装土方）常采用**多级横向表头**：第一行为定额编号，第二行（甚至更多行）为挖掘机斗容、自卸汽车吨位、土壤类别等属性，左侧第一列为费用项目（人工、材料、机械、基价等），中间区域为数值。此类结构不利于数据分析，需转换为**一维表**（每行一个定额子目，包含全部属性和费用数值）。

## 2. 核心转换思路
**将每一列（每个定额编号）拆成独立的一行**，同时将该列对应的多级表头属性（如斗容、吨位、土壤类别）附加到该行中，形成规整的“长格式”数据表。

## 3. 通用脚本设计原则
由于不同定额表可能存在以下差异：
- 表头层级数不同（2~4层）
- 属性行内容不同（有的包含单位、有的不包含）
- 左侧固定列数不同（可能有“序号”、“项目”、“单位”等）
- 不同定额的列数（定额子目数量）不固定

因此脚本需具备**自动识别**能力，不应硬编码行列位置。

### 3.1 通用处理流程
1. **读取表格原始数据**（支持 Excel、CSV 或从图片 OCR 后得到的文本表）。
2. **自动检测表头区域**：从第1行开始向下扫描，直到遇到第一行包含“人工”、“基价”等典型费用项目名称的行，该行之前的所有行视为表头行。
3. **提取每个定额编号列的完整属性**：
   - 获取所有定额编号（通常为纯数字或“数字+字母”），位于表头区域最后一行之上的某一行（常见为第一行）。
   - 对于每个定额编号列，收集其上方所有表头行对应单元格的值，按从上到下的顺序组合成属性列表（如 `['0.75', '8', 'Ⅰ-Ⅱ']`）。
4. **提取左侧费用项目区域**：识别“项目”列（通常包含“人工”、“材料”、“机械”等）和“单位”列（如果有），剩余列为数值列。
5. **执行逆透视**：将每个数值列（定额编号列）与左侧费用项目行交叉，生成初步的长格式数据（列：定额编号、费用项目、数值）。
6. **关联属性**：将步骤3得到的每个定额编号的属性列表附加到长格式数据中，每个属性成为一个独立列。
7. **输出标准一维表**：最终列结构为 `[定额编号, 属性1, 属性2, ..., 属性N, 费用项目, 数值]`（也可将费用项目展开为多列，视需求而定）。

### 3.2 关键技术点
- **表头边界识别**：通过正则匹配费用项目关键词（如“人工|工日|挖掘机|推土机|自卸汽车|基价”）定位数据区域起始行。
- **属性对齐**：如果表头存在合并单元格，需先用 `pandas` 或 `openpyxl` 的合并单元格处理函数进行前向填充（fill forward）。
- **动态属性列命名**：可按“属性1”、“属性2”命名，也可根据常见模式（如“斗容”、“吨位”、“土壤类别”）智能映射（需预定义词典）。

### 3.3 代码框架（Python + pandas）

```python
import pandas as pd
import re

def detect_header_rows(df_raw):
    """返回表头结束的行索引（数据区起始行）"""
    for i, row in df_raw.iterrows():
        row_str = ' '.join([str(v) for v in row.values if pd.notna(v)])
        if re.search(r'人工|工日|挖掘机|推土机|自卸汽车|基价', row_str):
            return i
    return 0

def extract_attributes_per_column(df_header, start_col, end_col):
    """
    对每个定额编号列，提取其上方所有表头行的值作为属性列表
    返回 dict {col_index: [attr1, attr2, ...]}
    """
    attrs = {}
    for col in range(start_col, end_col+1):
        col_attrs = []
        for row_idx in range(df_header.shape[0]):
            val = df_header.iloc[row_idx, col]
            if pd.notna(val):
                col_attrs.append(str(val).strip())
        attrs[col] = col_attrs
    return attrs

def convert_quote_table(file_path, sheet_name=0):
    # 1. 读取原始数据（保持原始格式，不设表头）
    df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    
    # 2. 检测数据区起始行
    data_start_row = detect_header_rows(df_raw)
    header_df = df_raw.iloc[:data_start_row, :]   # 表头区
    data_df = df_raw.iloc[data_start_row:, :]     # 数据区
    
    # 3. 识别左侧固定列（项目名称列）和数值列
    # 假设左侧固定列包含“人工”、“基价”等关键词，且列数固定为1或2（含单位列）
    # 这里简单处理：第一列是项目名称，第二列可能是单位，其余为数值列
    left_cols = []
    for col in range(data_df.shape[1]):
        col_vals = data_df.iloc[:, col].dropna().astype(str)
        if any(re.search(r'人工|基价|挖掘机', v) for v in col_vals):
            left_cols.append(col)
        else:
            break
    if not left_cols:
        left_cols = [0]   # 默认第一列为项目名称
    numeric_cols = [c for c in range(data_df.shape[1]) if c not in left_cols]
    
    # 4. 提取每个数值列的属性（从表头区）
    col_attrs = extract_attributes_per_column(header_df, numeric_cols[0], numeric_cols[-1])
    
    # 5. 逆透视数据区
    # 先构建项目名称和单位列（如果有两列则第二列为单位）
    if len(left_cols) == 1:
        id_vars = [data_df.columns[left_cols[0]]]  # 临时列名
        var_name = '定额编号'
        value_name = '数值'
    else:  # 有两列：项目、单位
        id_vars = [data_df.columns[left_cols[0]], data_df.columns[left_cols[1]]]
        var_name = '定额编号'
        value_name = '数值'
    
    # 由于原始 data_df 列是 RangeIndex，直接 melt
    df_melt = data_df.melt(id_vars=id_vars, value_vars=numeric_cols,
                           var_name='col_idx', value_name='数值')
    # 将 col_idx 映射为定额编号（从表头第一行获取）
    # 定额编号行通常位于 header_df 的第一行
    quote_ids = header_df.iloc[0, numeric_cols].values  # 假设第一行是定额编号
    col_to_id = {col: qid for col, qid in zip(numeric_cols, quote_ids)}
    df_melt['定额编号'] = df_melt['col_idx'].map(col_to_id)
    
    # 6. 添加属性列
    for attr_idx in range(max(len(v) for v in col_attrs.values())):
        attr_name = f'属性{attr_idx+1}'
        df_melt[attr_name] = df_melt['col_idx'].apply(
            lambda c: col_attrs.get(c, [''])[attr_idx] if attr_idx < len(col_attrs.get(c, [])) else ''
        )
    
    # 7. 整理输出
    df_melt.drop(columns=['col_idx'], inplace=True)
    # 可选：将费用项目展开为列（宽表形式）
    # 如需要宽表，使用 pivot_table
    # 这里直接输出长表便于后续处理
    return df_melt

# 使用示例
# df_result = convert_quote_table('定额表.xlsx')
# df_result.to_excel('转换结果.xlsx', index=False)