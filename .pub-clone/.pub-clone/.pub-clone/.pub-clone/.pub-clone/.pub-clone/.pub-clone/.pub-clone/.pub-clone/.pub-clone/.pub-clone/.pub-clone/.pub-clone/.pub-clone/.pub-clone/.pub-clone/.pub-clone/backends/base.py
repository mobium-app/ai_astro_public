"""Interfejs backendów LLM."""

from dataclasses import dataclass, field


@dataclass
class BackendResult:
    text: str = ""
    tool_calls: list = field(default_factory=list)


class Backend:
    name = "base"
    capabilities = set()

    def ready(self):
        return False

    def run(self, messages, *, tools=None, fmt=None, max_tokens=400, temperature=0.2,
            on_token=None):
        raise NotImplementedError
