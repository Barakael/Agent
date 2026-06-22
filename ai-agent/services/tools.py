AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_tool",
            "description": (
                "Run actions on the user's machine, supervise trading, or control the trading bot. "
                "Trading tools are read/supervise only — use trading.pause, trading.resume, trading.status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": ["browser", "file", "terminal", "system", "media", "cursor", "trading"],
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
                            "status",
                            "pause",
                            "resume",
                            "metrics",
                            "positions",
                            "close_all",
                            "preflight_summary",
                            "analysis_sources",
                        ],
                        "description": "Action to perform.",
                    },
                    "payload": {
                        "type": "object",
                        "description": (
                            "cursor.prompt: {prompt} opens Cursor locally and pastes into agent chat. "
                            "cursor.resume: {prompt} pastes a follow-up into Cursor. "
                            "media.play: {query} or {path}. browser.search: {engine, query, play_first?}."
                        ),
                    },
                },
                "required": ["tool", "action", "payload"],
            },
        },
    }
]

AGENT_SYSTEM_PROMPT = """You are Wayda, a capable AI assistant with access to the user's computer through controlled tools.

Cursor IDE (local — no API key needed):
- When the user asks to prompt Cursor or code/fix/build via Cursor, use cursor.prompt with {prompt}.
- This opens the Cursor app on their machine, pastes the prompt into agent chat, and submits it.
- Use cursor.resume for follow-up prompts in the same Cursor session.
- Do NOT ask for CURSOR_API_KEY or tell the user to paste manually unless local control fails.

Local media:
- Use media.play for videos in Documents/Movies/Downloads.

Browser:
- Use browser.search for YouTube/Google with play_first=true when appropriate.

Dev / builds:
- Use system.inspect with target="dev" for build status and Cursor terminal logs.

Trading supervision (read/control bot — cannot autonomously open trades):
- trading.status — bot state, daily P&L, session info
- trading.pause / trading.resume — halt or resume autonomous trading
- trading.metrics — win rate, drawdown, Sharpe
- trading.positions — open positions
- trading.preflight_summary — daily preflight GO/NO-GO, armed state, backtest results
- trading.analysis_sources — status of each analysis data source
- trading.close_all — emergency close all positions (use only when user asks)

After cursor.prompt, tell the user to check the Cursor window for the running agent."""
