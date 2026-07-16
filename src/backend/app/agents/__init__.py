"""LangGraph-based review agents (replaces Claude Code CLI)."""

__all__ = ["run_agent"]


def __getattr__(name: str):
    if name == "run_agent":
        from app.agents.runner import run_agent

        return run_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
