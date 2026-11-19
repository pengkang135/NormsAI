# NormsAI · 企业定额库

**中文** · [English](README.en.md)

NormsAI 是成本中心的企业定额库。可按册次和章节浏览定额、查看人材机消耗，并按价格包组价和导出 Excel。[正式站入口](https://checcost.com/norms/norms_browser.html)

## 在本地启动

准备 Git 和 Python 3.12 或 3.13。如果已经下载仓库，直接进入该目录并运行最后一行。

```bash
git clone https://github.com/pengkang135/NormsAI.git
cd NormsAI
python start.py
```

浏览器打开 [http://localhost:18080/norms_browser.html](http://localhost:18080/norms_browser.html)。平时在运行服务的终端按 `Ctrl+C` 停止。

- 如果 `18080` 正在使用，可运行 `python start.py --port 18180 --no-open`，再打开 [http://localhost:18180/norms_browser.html](http://localhost:18180/norms_browser.html)。
- 如果要测试 Excel 导出，在使用的 Python 环境中运行 `python -m pip install openpyxl`，然后重启服务。
- 查询页面由 `output/norms_browser.html` 提供，接口入口是 `start.py`。本地服务从 `db/` 读取 SQLite。缺少某册数据或价格包时，向成本中心索取对应的开发样本。[数据库目录](db/INDEX.md)

## 如何提交修改

1. **取得协作权限。** 把 GitHub 用户名和想改的内容发给仓库所有者。收到邀请后用同一账号接受。
2. **开自己的分支。** 从双方约定的版本开始。下面以仓库的默认分支 `master` 为例。
3. **在本地验证并推送。** 运行上面的启动命令检查改动。提交时只选本次改动的文件，数据用获准的开发样本。

```bash
git switch master
git pull --ff-only
git switch -c docs/norms-guide
# 修改并验证后，逐个添加改过的文件
git add README.md
git commit -m "docs: update NormsAI guide"
git push -u origin docs/norms-guide
```

4. **在 GitHub 提交 PR。** 打开[仓库](https://github.com/pengkang135/NormsAI)，点 **Compare & pull request**，确认目标分支，写明改了什么、怎样验证。界面改动可以附截图。若收到修改意见，在同一分支改完再推送，原 PR 会更新。仓库所有者负责合并和正式发布。

用 GitHub Desktop 时，在 **Current Branch → New Branch** 开分支。本地改好后点 **Commit to… → Publish branch → Preview Pull Request**，在 GitHub 完成提交。
