# TOPIK Review Queue Spec

本规范定义 `MASTER_REVIEW_QUEUE.md` 主队列表的状态语义和写回边界。脚本修复、审计和后续 backlog 调度都应以本文件为准。

## 1. 主表字段

主表为 `MASTER_REVIEW_QUEUE.md` 的 `## 4. 总复习队列`。

核心字段：

- `ID`：稳定唯一 ID。
- `类型`：`vocabulary` / `phrases` / `chunks` / `grammar` / `contrast` / `audit`。
- `当前R阶段`：`R0` 到 `R7`。
- `连续正确`：first-pass 正确连续次数。
- `错误次数`：first-pass wrong 次数。
- `上次复习`：最近一次 first-pass 写回日期。
- `下次复习`：下一次进入 review plan 的日期，或 `待安排`。
- `状态`：调度状态。

## 2. 状态定义

| 状态 | 含义 | `下次复习` 要求 | 是否进入自动 review plan |
|---|---|---|---|
| `active` | 正常 SRS 队列条目 | 必须是日期；若为 `待安排`，视为数据异常 | 是，有日期且到期时进入 |
| `high-frequency` | first-pass wrong/uncertain 或高频回炉条目 | 必须是日期；不得长期 `待安排` | 是，有日期且到期时进入 |
| `pending` | 已入库但尚未启动正式复习的条目 | 可以是 `待安排` | 否 |
| `archived` | 已归档，不再常规复习 | 可为空 | 否 |
| `suspended` | 暂停复习，等待人工处理 | 可为空或 `待安排` | 否 |

## 3. 调度规则

### correct

- first-pass `correct` 后，`连续正确 +1`。
- 按当前 R 阶段进入下一 R 阶段。
- `状态` 设为 `active`。
- `下次复习` 必须写入明确日期，除非达到归档条件。

### wrong

- first-pass `wrong` 后，`连续正确` 清零。
- `错误次数 +1`。
- `状态` 设为 `high-frequency`。
- 应安排次日复查。
- 当日错项回炉只作为练习记录，不覆盖 first-pass wrong。

### uncertain

- first-pass `uncertain` 后，`连续正确` 清零。
- `状态` 设为 `high-frequency`。
- 应安排次日复查。
- 当日错项回炉只作为练习记录，不覆盖 first-pass uncertain。

## 4. First-pass 与回炉边界

first-pass 是唯一用于推进 `MASTER_REVIEW_QUEUE.md` 的正式结果。

当日错项回炉、中文到韩语补充练习、主动输出练习可以写入 daily log，但不得覆盖同一天 first-pass 的 `correct` / `wrong` / `uncertain`。

示例：

- first-pass 为 `wrong`，当日回炉后答对：MASTER 仍按 `wrong` 安排次日复查。
- first-pass 为 `uncertain`，当日回炉后答对：MASTER 仍按 `uncertain` 安排次日复查。
- 补充练习错项不得反向改写主复习 first-pass 结果。

## 5. 待安排规则

允许 `待安排` 的情况：

- `pending` 条目。
- `suspended` 条目。
- 尚未进入正式复习的导入材料。

不允许长期 `待安排` 的情况：

- `active / 待安排`。
- `high-frequency / 待安排`。

上述两类应由审计脚本报告，不应由生成 review plan 的脚本静默忽略。

## 6. 高频回炉区

`## 5. 高频回炉区` 是派生视图，不应作为权威数据源。

权威状态以 `## 4. 总复习队列` 主表为准。若第 5 节与主表不一致，应优先修复脚本或重建派生视图，不应手工同时维护两套状态。

## 7. 安全要求

- 写回脚本必须支持 `--dry-run`。
- `--dry-run` 不得修改 `MASTER_REVIEW_QUEUE.md`、daily log 或 review plan。
- 写回脚本必须只解析精确 review result 表头：
  `ID / 内容 / 类型 / 原R阶段 / 结果 / 错因 / 新等级 / 备注`。
- 如果 daily log 表示 `总复习数量 > 0`，但解析结果为 0 条，脚本必须报错退出。
- backlog 调度必须由单独命令分批执行，不得在普通 review plan 生成时自动吞入全部无日期条目。
