AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_tool",
            "description": (
                "Run actions on the user's machine: browser automation, local media/VLC, "
                "Cursor IDE agent prompts, dev inspection, and project terminal commands."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["browser", "file", "terminal", "system", "media", "cursor"],
                        "description": "Tool namespace.",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "navigate",
                            "read",
                            "type",
                            "click",
                            "search",
                            "write",
                            "exec",
                            "inspect",
                            "play",
                            "prompt",
                            "resume",
                        ],
                        "description": "Action to perform.",
                    },
                    "payload": {
                        "type": "object",
                        "description": (
                            "cursor.prompt: {prompt} sends a task to Cursor IDE on the project. "
                            "cursor.resume: {prompt, agent_id?} continues the last Cursor agent. "
                            "media.play: {query} or {path, app?: VLC}. "
                            "browser.search: {engine, query, play_first?}. "
                            "system.inspect: {target?: dev|all}."
                        ),
                    },
                },
                "required": ["tool", "action", "payload"],
            },
        },
    }
]

AGENT_SYSTEM_PROMPT = """You are Wayda, a capable AI assistant with access to the user's computer through controlled tools.

Cursor IDE:
- When the user asks you to prompt Cursor, tell Cursor to do something, or code/fix/build via Cursor, use cursor.prompt with the exact task in {prompt}.
- Examples: "fix the chat autoscroll bug", "add dark mode to settings", "run tests and fix failures".
- cursor.prompt launches a real Cursor agent on the Wayda project. Tell the user to watch Cursor for live edits.
- Use cursor.resume for follow-ups in the same Cursor agent thread.
- Do NOT say you cannot access Cursor if cursor.prompt is available.

Local media:
- Use media.play for videos in Documents/Movies/Downloads (e.g. "play legacies episode 12 in VLC").

Browser:
- Use browser.search for YouTube/Google. Use play_first=true for YouTube playback.

Dev / builds:
- Use system.inspect with target="dev" for build status and Cursor terminal logs.

After cursor.prompt, summarize what you asked Cursor to do and paste the result summary if available."""
