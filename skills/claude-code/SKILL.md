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

Look for keywords like: "code", "write", "build", "implement", "fix", "debug", "refactor", "create a script", "make a program", or any request that involves programming.

## When NOT to Use

Do not use `claude_code` for:
- General knowledge questions
- Web searches
- File reading (use your built-in read_file tool)
- Simple shell commands
- Memory/notes operations

## How to Use

1. Identify that the user's request is a coding task.
2. Formulate a clear, detailed prompt describing exactly what needs to be done.
3. Call the `claude_code` tool with the task description as the `task` parameter.
4. Report the result back to the user.

## Writing Good Task Prompts

Be specific in the task you send to Claude Code. Include:
- What to build or change
- Which files or languages are involved
- Any constraints or requirements the user mentioned

### Examples

**User says:** "Build me a Python script that scrapes headlines from Hacker News"
**Task:** "Create a Python script called hn_scraper.py that scrapes the top 30 headlines from Hacker News (https://news.ycombinator.com/) using the requests and beautifulsoup4 libraries. Print each headline with its rank and URL."

**User says:** "Fix the bug in my Flask app"
**Task:** "Look at the Flask application code and identify any bugs. Fix them and explain what was wrong."

**User says:** "Add error handling to server.py"
**Task:** "Add proper error handling to server.py — wrap route handlers in try/except blocks, return appropriate HTTP status codes, and log errors."
