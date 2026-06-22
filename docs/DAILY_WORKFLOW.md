# TOPIK Daily Workflow

## Morning / Start of study

1. Run:
   python scripts/topikctl.py today --date YYYY-MM-DD

2. If due > 50:
   - no new content
   - no backlog
   - review only

3. If due <= 20 and previous wrong/uncertain <= 5:
   - light new content allowed

## During study

1. First-pass result must be recorded as correct/wrong/uncertain.
2. Immediate 回炉 is allowed.
3. 回炉 correct does not overwrite first-pass wrong/uncertain.

## After GPT teaching

1. Fill templates/gpt_session_summary_template.md.
2. Run ingest_gpt_session.py --dry-run.
3. Apply only after dry-run looks correct.

## End of day

1. Write daily log.
2. Run update_review_queue.py YYYY-MM-DD --dry-run.
3. Apply update only after dry-run parsed result count matches expected.
4. Generate next-day review plan only after queue update.
5. Run topikctl check.
6. Commit and push.
