AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_tool",
            "description": (
                "Run a computer action on the user's machine. Use browser tools to open "
                "or read web pages, file tools to read/write in the agent workspace, and "
                "terminal tools to run safe shell commands in that workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["browser", "file", "terminal"],
                        "description": "Tool namespace.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["navigate", "read", "write", "exec"],
                        "description": "Action to perform.",
                    },
                    "payload": {
                        "type": "object",
                        "description": (
                            "Action payload. browser.navigate: {url}. browser.read: {url}. "
                            "file.read: {path}. file.write: {path, content}. "
                            "terminal.exec: {command}."
                        ),
                    },
                },
                "required": ["tool", "action", "payload"],
            },
        },
    }
]

AGENT_SYSTEM_PROMPT = """You are Wayda, a capable AI assistant with access to the user's computer through controlled tools.

When the user asks you to open a website, browse the web, read or write files, inspect folders, or run shell commands, use the execute_tool function.

Guidelines:
- Prefer browser.navigate when the user wants a page opened in their browser.
- Use browser.read when you need page content without opening a visible browser tab.
- Use file.read and file.write only inside the agent workspace unless the user clearly needs local project files there.
- Use terminal.exec for safe inspection commands like ls, pwd, cat, grep, and find.
- After using tools, summarize what you did and share useful results.
- Ask for clarification if a request is ambiguous or potentially destructive.
- Do not claim you ran a tool unless you actually called execute_tool."""
