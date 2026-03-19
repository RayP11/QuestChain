<div align="center"><img src="../assets/scheduler.png" alt="" width="280"/></div>

# Telegram Setup

QuestChain runs alongside the CLI as a Telegram bot, giving you remote access from your phone. The same conversation thread and memory is shared between CLI and Telegram — switch between them mid-conversation.

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
| `/start` | Begin or resume a conversation |
| `/new` | Start a fresh conversation thread |
| `/quest` | Two-step wizard to create a new quest (title → content) |

---

## Voice messages

If Kokoro TTS is configured, QuestChain sends voice messages on Telegram in addition to text — the same response delivered as audio.

---

!!! note
    The Telegram bot only accepts messages from your user ID. Anyone else messaging the bot gets no response.
