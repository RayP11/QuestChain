<div align="center"><img src="../assets/oracle.png" alt="" width="280"/></div>

# Quests

Quests let your agent work in the background — autonomously, without you watching. Drop a task into a file, and your agent picks it up, completes it, and reports back.

---

## How it works

Every 60 minutes (configurable), QuestChain checks for pending quests, picks the first one, and gets to work. When it's done, the quest file is deleted and the result is shown in the chat — and sent to your phone if Telegram is set up.

You don't need to be at your computer. You don't need to watch it. It just works.

---

## Writing a quest

A quest is just a plain text file describing what you want done. Drop it in `workspace/quests/` and your agent will find it.

```
workspace/quests/find-api-docs.md
```

```
Find the REST API docs for the weather service and save a summary to workspace/memory/weather-api.md
```

Write it like you'd write a note to a capable assistant. Be specific about what you want and where to save results.

---

## More quest examples

```
Research the top 5 project management tools in 2026.
Compare them on price, features, and offline support.
Save the comparison to workspace/memory/pm-tools.md
```

```
Go through all the files in workspace/inbox/ and write
a one-sentence summary of each. Save to workspace/memory/inbox-summary.md
```

```
Check the QuestChain GitHub repo for any new open issues
and summarize them in workspace/memory/issues.md
```

---

## Managing quests

Type `/quest` in the chat to open the quest manager — create, view, and delete quests without leaving the app.

---

