---
name: claude-code
description: Delegate coding tasks to Claude Code, an expert AI coding agent powered by Anthropic
---

# Claude Code Skill

## When to Use

Use the `claude_code` tool when the user asks you to:
- Write, create, or generate code
- Debug or fix code issues
- Refactor or improve existing code
- Create new files or projects
- Make changes to a codebase
- Explain code in detail
- Write tests
- Review or analyze code

Look for keywords like: "code", "write", "build", "implement", "fix", "debug", "refactor", "create a script", "make a program", "review", or any request that involves programming.

## When NOT to Use

Do not use `claude_code` for:
- General knowledge questions
- Web searches
- File reading (use your built-in read_file tool)
- Simple shell commands
- Memory/notes operations

## Parameters

### `task` (required)
The coding task or prompt. Be specific about what to build/change, which files are involved, and any constraints.

### `complexity` (optional, default: `"medium"`)
Controls which Claude model and timeout to use:

| Value | Model | Timeout | Use When |
|-------|-------|---------|----------|
| `"simple"` | Haiku (fast) | 5 min | Explanations, small edits, quick code questions |
| `"medium"` | Sonnet (capable) | 10 min | Most coding tasks, bug fixes, new features |
| `"complex"` | Sonnet (capable) | 15 min | Large refactors, multi-file changes, complex implementations |

### `mode` (optional, default: `"code"`)
Controls what Claude Code is allowed to do:

| Value | Permissions | Use When |
|-------|------------|----------|
| `"code"` | Read + write/edit files | You need code changes made (default) |
| `"review"` | Read-only access | Code review, analysis, understanding code without changing it |

### `context` (optional)
Additional project context to include with the task. Pass relevant information from the conversation that Claude Code might need, such as error messages, user requirements, or file paths mentioned earlier.

## Examples

### Simple task — explain code
```
claude_code(
    task="Explain what the create_genie_agent function does in genie/agent.py",
    complexity="simple",
    mode="review"
)
```

### Medium task — fix a bug
```
claude_code(
    task="Fix the bug where web_search results are not being displayed correctly",
    complexity="medium",
    mode="code",
    context="The user reported that search results show 'None' instead of snippets. Error traceback points to tools/web_search.py line 15."
)
```

### Complex task — implement a feature
```
claude_code(
    task="Add a new REST API endpoint that exposes Genie as an HTTP service with streaming responses",
    complexity="complex",
    mode="code",
    context="Should use FastAPI, support SSE streaming, and integrate with the existing agent.py create_genie_agent function."
)
```

### Code review
```
claude_code(
    task="Review the Telegram bot integration for security issues and potential improvements",
    complexity="medium",
    mode="review"
)
```

## Writing Good Task Prompts

Be specific in the task you send to Claude Code. Include:
- What to build or change
- Which files or languages are involved
- Any constraints or requirements the user mentioned
- Use `context` to pass error messages, stacktraces, or conversation details
