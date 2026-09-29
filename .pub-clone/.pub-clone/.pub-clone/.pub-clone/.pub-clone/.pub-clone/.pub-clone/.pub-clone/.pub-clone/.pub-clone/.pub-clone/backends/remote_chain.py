"""Backend zdalny „łańcuch": ASTRO(OpenCode) -> DeepSeek -> Grok -> Gemini -> OpenRouter -> PC.

Rejestrowany przy `ASTRO_REMOTE=1`, gdy nie podano pojedynczego `ASTRO_REMOTE_URL`. Klucze czyta
`remote_support` z `ASTRO_API_FILE` (`/etc/astro-secrets/API`). Używany jako ostatnia deska ratunku
(polityka `fresh`/`heavy`), nigdy do prostych komend — patrz `core/dispatch`.
"""

from .. import remote_support
from .base import Backend, BackendResult


class RemoteChainBackend(Backend):
    name = "remote"
    capabilities = {"chat", "tools", "json", "plan", "fresh"}
    model = "chain"

    def __init__(self, chain=None, name=None):
        self.chain = chain
        if name:
            self.name = name

    def _active_chain(self):
        # Domyślny łańcuch zawiera PC-Kali (wsparcie runtime w trybie offline). Tryb premium
        # przekazuje własny łańcuch (OpenCode Go pierwszy), więc `self.chain` ma priorytet.
        return self.chain or remote_support.provider_chain(include_pc=True)

    def endpoint(self):
        chain = self._active_chain()
        return chain[0].endpoint() if chain else ""

    def ready(self):
        try:
            chain = self._active_chain()
            if not chain:
                return False
            if any(p.label != "pc" for p in chain):
                return True  # jest choć jedno źródło chmurowe z kluczem
            return remote_support._pc_online(chain[0].url)
        except Exception:
            return False

    def run(self, messages, *, tools=None, fmt=None, max_tokens=400, temperature=0.2,
            on_token=None):
        result = remote_support.ask_full(messages, tools=tools, fmt=fmt, max_tokens=max_tokens,
                                         temperature=temperature, chain=self.chain)
        if result is None:
            raise RuntimeError("żaden dostawca zdalny nie odpowiedział")
        text, label, _usage, calls = result
        self.model = label
        return BackendResult(text=text, tool_calls=calls)
