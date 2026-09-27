<div align="center"><img src="../assets/scheduler.png" alt="" width="280"/></div>

# Telegram Setup

QuestChain runs alongside the CLI as a Telegram bot, giving you remote access from your phone. Agent definitions and cron jobs are shared across interfaces. Each Telegram chat has its own selected agent and conversation; specialist results retain their author.

---

## Setup

Run `/telegram` inside QuestChain and it walks you through the two-step wizard:

**Step 1 — Get a bot token:**

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token it gives you

**Step 2 — Get your user ID:**

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Copy your numeric user ID from the response

Paste both into the `/telegram` wizard. Credentials are saved automatically to `~/.questchain/.env`.

---

## Starting with Telegram

Restart QuestChain after setup and the bot starts automatically alongside the CLI:

```bash
questchain start
```

No extra flags needed — if credentials are saved, the bot starts.

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Show the introduction and command list |
| `/help` | Show all commands |
| `/new` | Start a fresh conversation and clear the previous run selection |
| `/model` | Show the selected agent's current model, including its override |
| `/cron` | List cron jobs and management commands |
| `/agents` | Select, create, edit, or explicitly migrate a legacy agent |
| `/runs [run ID]` | List this conversation's runs or read one saved result |
| `/history [conversation ID]` | List this chat's saved conversations or resume one |
| `/cancel [run ID]` | Cancel a run in this conversation; without an ID, also cancels agent creation |
| `/retry [run ID]` | Retry the latest run or a specified run in this conversation |
| `/tools` | Show the selected agent’s configured tools |
| `/level` | Show agent level and achievements |
| `/stats` | Show agent metrics: prompts, tokens, errors |
| `/onboard` | Re-run the onboarding conversation |

Use `/runs page N` or `/history page N` to browse more than 20 entries. `/history ID` reopens a saved conversation and shows its latest 10 requests and answers with the original agent names. `/runs ID` retrieves a full saved result, including any error or partial response.

History is restricted to the current Telegram chat and survives restarting QuestChain. `/new` keeps the old history, but retry and cancellation apply only to the new conversation. Resume an older conversation with `/history ID` before retrying one of its runs.

---

## Voice messages

If Kokoro TTS is configured, QuestChain sends voice messages on Telegram in addition to text — the same response delivered as audio.

---

!!! note
    The Telegram bot only accepts commands and messages from your configured user ID. Other users receive a private-bot rejection; they cannot read conversations or run tasks.

See [Cron Jobs](cron-jobs.md) for create, edit, pause, resume, run, and delete syntax.
