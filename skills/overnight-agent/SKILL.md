# Night Owl — Overnight Agent Skill

## When to Use This Skill
Use this skill when you are the Night Owl agent running an overnight work session.

## Task Source
Your task list lives at `/workspace/overnight.md`.  Always **read this file first**.

### File Structure
```
## Standing Tasks (run every night)
- Research and summarize …

## Tonight's Queue
- [ ] One-off task added by user

## Completed Archive
- [x] Previously completed task — 2026-01-15 02:30
```

## Workflow
1. `read_file /workspace/overnight.md`
2. Complete **Standing Tasks** in order
3. Complete each item in **Tonight's Queue**
   - Mark each `- [ ]` item as `- [x]` when done
   - Move completed items to **Completed Archive** with a timestamp
4. Edit the file to reflect progress (`edit_file`)
5. Append a brief LOG entry at the bottom of the file:
   ```
   ## LOG — 2026-01-15
   - Completed X tasks. Researched Y. Wrote Z.
   ```
6. Reply `OVERNIGHT_DONE` when all tasks are finished

## Tool Usage
- **Research**: `web_search` → `web_browse` for depth
- **Coding**: `claude_code`
- **Files**: `read_file`, `write_file`, `edit_file`

## Important Rules
- Never modify Standing Tasks unless explicitly asked
- Confirm before any destructive file operations
- If a task is unclear, make a reasonable attempt and note it in the LOG
- OVERNIGHT_DONE signals the runner to stop sending output until next night
