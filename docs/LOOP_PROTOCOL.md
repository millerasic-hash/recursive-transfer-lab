# Adaptive Recursive Transfer Protocol

## Objective

发现跨学科重复轮子，并把可迁移候选落成可验证的 GitHub 实验。

## Loop

```text
Observe -> Normalize -> Graph -> Compare -> Hypothesize -> Verify -> Record -> Reweight -> Refrequency
```

## Record Types

- `Observation`: 直接观察到的事实。
- `Inference`: 基于事实的推断。
- `Decision`: 本轮行动选择。
- `Record`: 写入状态文件的内容。

只有 `verified` 状态可以被下一轮当作事实继承。

## Truth Surfaces

- OpenAlex API response
- GitHub CLI repo inventory
- local report JSON
- `manifest.json`
- `progress.json`
- `generation-status.md`

## Candidate Quality

候选迁移要同时记录：

- `problem`: 原领域问题。
- `method`: 可迁移方法。
- `implementation`: GitHub 或代码实现线索。
- `evidence`: 证据 URL、DOI、repo URL。
- `risk`: 迁移风险。
- `confidence`: 0 到 1 的粗置信分。

## Circuit Breaker

停止递归扩展的条件：

- 同一错误连续出现 3 次。
- 状态文件与真实接口冲突。
- 需要账号隐私或凭据。
- 要执行破坏性 GitHub 操作。
- 缺少证据但系统试图标记完成。

## Frequency Rule

启动期高频，稳定后降频。

```text
new signals + contradictions + missing evidence -> increase frequency
verified stable rounds + low signal density -> decrease frequency
```

