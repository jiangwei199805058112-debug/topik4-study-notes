# TOPIK4 Review System v3

## 1. 核心原则

v3 在现有 `daily/`、`review/`、`MASTER_REVIEW_QUEUE.md` 之外新增一层“学过总表”。以后处理新材料时，先抽取词汇、搭配、语法和易混点，再查询 master 表。

流程：

1. 新材料先抽取词汇、搭配、语法、易混点。
2. 抽取后先查 `data/master/grammar_master.csv` 和 `data/master/vocabulary_master.csv`。
3. 已学过项目只更新 `source_refs`、`last_seen_date`、必要时提高 `ask_priority`。
4. 未学过项目才新增稳定 ID。
5. 用户主动标记“还要记住”的项目，`ask_priority` 至少为 `medium`。
6. 干扰项、易混项或用户反复错项，`ask_priority=high`。
7. 复习提问由 `mastery_level`、`ask_priority`、`status` 共同决定。
8. 连续多次正确后降频；错误或 uncertain 后提升优先级。
9. `grammar/MASTER_GRAMMAR_TABLE.md` 和 `vocabulary/MASTER_VOCABULARY_TABLE.md` 由 CSV 自动生成。
10. 新材料中出现的已学内容，应优先作为“复用旧知识”提问，不重复新增。
11. 多次答对的项目可以转为低频或暂停高频提问。

## 2. 数据文件

- `data/master/grammar_master.csv`：机器可读语法总表。
- `data/master/vocabulary_master.csv`：机器可读单词/搭配总表。
- `data/master/review_events.csv`：后续结构化复习事件日志，用于防止同一天同一项目重复计数。
- `grammar/MASTER_GRAMMAR_TABLE.md`：面向背诵的语法总表，由脚本生成。
- `vocabulary/MASTER_VOCABULARY_TABLE.md`：面向背诵的单词/搭配总表，由脚本生成。

## 3. 提问优先级规则

| 情况 | 处理 |
|---|---|
| 新增项目 | `mastery_level=1`, `ask_priority=medium`, `status=active` |
| 用户主动标记“还要记住” | `ask_priority` 至少 `medium` |
| 干扰项/易混项 | `ask_priority=high` |
| 一次 wrong | `ask_priority=high`, `status=active` |
| 一次 uncertain | 至少保持 `medium` |
| 连续答对 3 次 | 可降为 `medium` |
| 连续答对 5 次 | 可降为 `low` 或 `status=low_frequency` |
| 连续答对 8 次且 14 天内没错 | `status=mastered`, `ask_priority=suspended` |
| 高频错 2 次以上 | 加入“易混/错点专项” |

当前 master CSV 只有累计 `correct_count`、`wrong_count`、`uncertain_count`，无法单独判断严格的“连续”。因此 `scripts/update_mastery_from_daily.py` 采用保守累计策略；未来若需要精确连续判断，应以 `data/master/review_events.csv` 作为事件日志扩展。

## 4. 本次来源

- 来源名：`TOPIK_BASIC_090_Q01_Q11`
- 日期：`2026-06-21`
- 类型：`reading_basic_review`
- 备注：用户对 TOPIK 基础题 1-11 做精读复习，并主动标记了一批仍需记忆的语法、词汇、搭配和干扰项。

这批内容只进入 master 表作为精读来源，不作为主复习结果写入 `MASTER_REVIEW_QUEUE.md`，也不运行历史日期的 `update_review_queue.py`。

## 5. 常用命令

```bash
python scripts/build_master_tables.py --dry-run
python scripts/build_master_tables.py
python scripts/query_learned_items.py --grammar "-기 나름이다"
python scripts/query_learned_items.py --vocab "승강장"
python scripts/query_learned_items.py --text "꽃이 피기 시작하는 걸 보니 봄이 온 모양이다"
```

结构化复习结果更新示例：

```csv
date,item_type,item_key,result,source_ref
2026-06-21,grammar,-기 나름이다,correct,TOPIK_BASIC_090_Q01_Q11
2026-06-21,vocab,숨소리,wrong,TOPIK_BASIC_090_Q01_Q11
```

```bash
python scripts/update_mastery_from_daily.py --input path/to/results.csv --dry-run
python scripts/update_mastery_from_daily.py --input path/to/results.csv
```
