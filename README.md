# Recursive Transfer Lab

自动化递归组合迁移实验。

目标不是穷举论文和 GitHub，而是建立一个可以马上运行的小型循环：

```text
OpenAlex 公开论文池 + GitHub 可执行知识库
-> 抽取 Problem / Method / Evidence / Failure Mode / Repo Signal
-> 组合候选
-> 验证证据
-> 记录状态
-> 调整下一轮观察频率
```

## 当前范围

- `scripts/run_loop.py` 默认只读 GitHub 仓库清单。
- `scripts/run_loop.py` 默认只读 OpenAlex API。
- 本项目已进入 GitHub 托管，用来沉淀实验协议、报告和仓库管理建议。
- GitHub 管理动作必须写入正式状态文件，避免把一次性聊天结论当事实。
- 不上传 token、缓存、大文件或论文全文。

远端仓库：

- `https://github.com/millerasic-hash/recursive-transfer-lab`

## 快速运行

```bash
python3 scripts/run_loop.py
```

输出位置：

- `reports/loop/latest_summary.md`
- `reports/loop/state.json`
- `reports/github_inventory.md`
- `reports/transfer_candidates.json`

## 真相源

本项目以这些文件判断当前状态：

- `manifest.json`
- `progress.json`
- `generation-status.md`
- `reports/loop/state.json`
- `reports/loop/latest_summary.md`

聊天结论只能当线索，不能当状态源。

## GitHub 管理目标

本项目会生成 GitHub 管理建议；已授权时可以执行低风险整理：

- 哪些 repo 缺少 topics
- 哪些 repo 缺少 license
- 哪些 repo 适合加 `CITATION.cff`
- 哪些 repo 可能该归档
- 哪些 repo 适合成为论文实现层或实验底座
