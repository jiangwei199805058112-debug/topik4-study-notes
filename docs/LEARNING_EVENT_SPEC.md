# Learning Event Spec

## 为什么要有 learning events

记录每天和 GPT 学过的内容、做过的题、错过的点、诊断结果，让第二天学习可以根据真实弱点安排。

学习事件层只记录事实，不直接修改 `MASTER_REVIEW_QUEUE.md`。正式 SRS 推进仍以 daily log 中的 first-pass 结果和队列脚本为准。

## 文件

- `data/learning_events.jsonl`：记录 GPT 精讲、语法理解、错因、诊断结论、异常审校。
- `data/review_events.jsonl`：记录复习、测验、生成题结果，可以是单题事件，也可以是无法精确还原 ID 时的 aggregate summary。
- `data/exam_diagnostics/topik_score_log.md`：集中记录 TOPIK 听力、阅读、写作诊断分数。
- `data/exam_diagnostics/*.md`：单次考试诊断细节。

## event_type

| event_type | 含义 |
|---|---|
| `exam_diagnosis` | 一次听力/阅读/写作诊断 |
| `grammar_learned` | 学到一个语法点 |
| `vocabulary_learned` | 学到一个词 |
| `chunk_learned` | 学到一个句型块 |
| `contrast_learned` | 学到一个易混对比 |
| `review_result` | 复习结果 |
| `generated_question_result` | 生成题结果 |
| `audit_note` | 审校/异常记录 |

## result 允许值

- `correct`
- `wrong`
- `uncertain`
- `learned`
- `diagnosed`
- `audit`
- `skipped`

## direction 允许值

- `ko_to_zh`
- `zh_to_ko`
- `listening`
- `reading`
- `writing`
- `mixed`

## skill_tags 例子

- `grammar_equivalence`
- `sentence_structure`
- `context_inference`
- `sequence_logic`
- `long_reading`
- `fact_check`
- `main_idea`
- `detail_matching`
- `writing_sentence`
- `writing_structure`
- `listening_keyword`
- `listening_long_dialogue`

## 推荐字段

```json
{
  "date": "2026-06-21",
  "event_type": "grammar_learned",
  "source": "GPT",
  "item_id": null,
  "ko": "-(으)ㄹ 만큼",
  "zh": "到……程度",
  "context": "숨소리가 들릴 만큼 조용해졌다",
  "exam": "TOPIK II 83",
  "section": "reading",
  "question_no": 3,
  "direction": "reading",
  "result": "learned",
  "skill_tags": ["grammar_equivalence", "sentence_structure"],
  "notes": "与 -ㄹ 정도로 意义接近。"
}
```

## 去重键

基础去重键：

```text
date + event_type + exam + section + question_no + ko + direction
```

如果新事件与已有事件的去重键相同，导入脚本应跳过，不重复写入。

## first-pass 与回炉边界

first-pass wrong/uncertain 不被当天回炉 correct 覆盖。

回炉结果可以写入 `learning_events` / `review_events`，但用于说明“已回炉”，不改变 first-pass 记录。

如果无法精确还原每个复习项的 ID 和结果，可以只写 aggregate summary；不得伪造 `item_id`。
