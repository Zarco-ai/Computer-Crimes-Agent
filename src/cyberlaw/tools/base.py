"""Tool plumbing: a uniform result type and the registry the agent sees.

Every tool returns a :class:`ToolResult` whose ``cites`` field lists the
provisions it surfaced. The citation verifier consumes exactly that, so a
tool can never put a citation in front of the model without also making it
verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..schemas import CostRecord, Retrieved


@dataclass
class ToolResult:
    """What a tool hands back to the agent loop."""

    # Text shown to the model. Statutory language is always verbatim.
    content: str
    # Citations this result legitimises, e.g. ["33.02(b-2)(4)"].
    cites: list[str] = field(default_factory=list)
    # Structured hits, surfaced in the UI as sources.
    sources: list[Retrieved] = field(default_factory=list)
    cost: CostRecord = field(default_factory=CostRecord)
    summary: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.summary:
            first = self.content.strip().splitlines()[0] if self.content.strip() else ""
            self.summary = (first[:120] + "…") if len(first) > 120 else first


@dataclass
class Tool:
    """A callable plus the JSON schema advertised to the model."""

    name: str
    description: str
    parameters: dict
    fn: Callable[..., ToolResult]

    def spec(self) -> dict:
        """OpenAI tool-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __call__(self, **kwargs: Any) -> ToolResult:
        return self.fn(**kwargs)


class ToolRegistry:
    """Name -> Tool, with the specs the agent passes to the API."""

    def __init__(self, tools: list[Tool]):
        self._tools = {t.name: t for t in tools}

    def specs(self) -> list[dict]:
        return [t.spec() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def call(self, name: str, arguments: dict) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                content=f"No such tool: {name}. Available: {', '.join(self.names())}.",
                error="unknown_tool",
                summary=f"unknown tool {name}",
            )
        try:
            return tool(**arguments)
        except TypeError as exc:
            return ToolResult(
                content=f"Invalid arguments for {name}: {exc}",
                error="bad_arguments",
                summary=f"bad arguments for {name}",
            )
        except Exception as exc:  # surfaced to the model so it can recover
            return ToolResult(
                content=f"{name} failed: {exc}",
                error="tool_error",
                summary=f"{name} error: {exc}",
            )
