# Models

QuestChain works with any model available in Ollama. These are the most tested.

---

## Tested models

| Model | VRAM | Notes |
|---|---|---|
| `qwen3:8b` | ~6 GB | **Default.** Fast, excellent tool calling, native thinking |
| `qwen3:4b` | ~3 GB | Compact. Solid tool calling, native thinking |
| `qwen3.5:9b` | ~7 GB | Strong tool calling across complex multi-step tasks |
| `qwen3.5:4b` | ~3.5 GB | Lightweight, reliable tool calling |
| `qwen3:1.7b` | ~2 GB | Ultra-light. Runs on CPU or minimal VRAM |

```bash
questchain start -m <any-model>   # use any model installed in Ollama
```

---

## Why small models work well here

Most agent frameworks are designed for large frontier models — they load every tool, every instruction, and every option into a single massive prompt. Small models struggle with that.

QuestChain does the opposite. Each agent is focused on a narrow role with only the tools it needs. Less noise means cleaner decisions. A 4B model that knows it's a researcher — and only has research tools — will consistently outperform a generalist model drowning in options.

**QuestChain works great from 4B models and up.** If you have more VRAM, larger models work even better — more capability, same focused approach. The framework scales with your hardware.

---

## Pulling a model

```bash
ollama pull qwen3:8b     # default
ollama pull qwen3:4b     # 3 GB VRAM
ollama pull qwen3:1.7b   # minimal hardware
```

Any model pulled into Ollama is immediately available to QuestChain via `-m`.

---

## No coding model?

The Builder class delegates programming tasks to [Claude Code](https://claude.ai/code) via subprocess — so your local model doesn't need to be a coding specialist. If you don't have Claude Code, try `deepseek-coder-v2:16b` for maximum capability or `qwen2.5-coder:7b` for a lighter option.
