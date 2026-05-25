# GitHub Organization Rules

## Purpose

把 GitHub 当成可执行知识库管理，而不是只当代码备份。

## Repository Classes

- `lab`: 实验项目，可快速变化。
- `product`: 可持续维护项目。
- `archive`: 已完成或不再维护，只保留证据。
- `paper-code`: 对应论文、报告、实验或可引用软件。
- `asset-heavy`: 只保留清单和轻量脚本，大文件不要进 Git。

## Required Files For Important Repos

- `README.md`
- `LICENSE`
- `.gitignore`
- `docs/`
- `reports/` 或 `examples/`
- `CITATION.cff` when the repo is research software

## Topics

每个重要 repo 至少应有 3 个 topics：

```text
domain
method
status
```

示例：

```text
research-software, openalex, github, recursive-agent, experiment
```

## No Heavy Artifacts

不要上传：

- 模型权重
- 引擎二进制
- 大型图片缓存
- node_modules
- 临时浏览器输出
- 原始论文全文批量缓存

上传：

- 源码
- 配置
- 小样本
- 报告
- manifest / progress / status

## GitHub Actions

本项目后续适合加最小 CI：

```text
python3 scripts/run_loop.py --offline
```

先保证脚本能跑，再考虑定时化。

