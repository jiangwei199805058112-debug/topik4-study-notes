# TOPIK Listening Bank Spec

## Scope

This directory stores structured TOPIK II listening practice data without copying raw copyrighted PDFs into the repository.

## Files

- `metadata.json`: source paths, extraction status, and copyright note.
- `answer_key.json`: question number to answer mapping.
- `attempt_YYYY-MM-DD.json`: one user attempt and scoring summary.
- `questions.json`: per-question metadata, answer, user result, source page, summary, and linked learning item IDs.
- `learning_items.json`: extracted vocabulary, phrases, chunks, grammar, and contrast items ready to merge into the review queue.
- `notes_YYYY-MM-DD.md`: human-readable study notes and priority plan.
- `OCR_TODO.md`: pages or ranges that need reliable OCR or user transcription.

## Queue Integration

Learning items are merged into `MASTER_REVIEW_QUEUE.md` by exact `(type, content)` match. Existing rows receive the listening bank source; new rows start at `R0` with `next_review = 2026-06-19`.
