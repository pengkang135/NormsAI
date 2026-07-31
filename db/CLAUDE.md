# CLAUDE.md — Norms-AI/db 定额数据库目录

## 定位

本目录是**只读调用仓库**。其他项目（清单套价、BOQ 询价等）通过 sqlite MCP 跨目录查询这里的数据库，查询结果回到调用方自己的项目目录处理。

**本目录不参与任何产出流程**。其他项目不得在此目录或其父目录（Norms-AI/）下生成文件。

## 规则

- **仅允许存在**: `.sqlite` 数据库文件、`backup/*.bak` 备份文件、`INDEX.md`、本 `CLAUDE.md`
- **禁止写入**: 任何文件都不得在此目录创建。脚本、导出、中间数据、日志、截图等全部禁止
- **调用方**在自己的项目 `temp/` 目录下生成临时文件，不在这里生成
- 查询走 sqlite MCP，结果输出到终端，不落盘到本目录

## 使用方式

```sql
-- 跨目录查询示例（其他项目中执行）
ATTACH 'F:/BaiduSyncdisk/2.清单定额/Norms-AI/db/企业定额_A册_建筑装饰.sqlite' AS norms;
SELECT * FROM norms.quota_item WHERE 定额编号 LIKE '0104%';
```
