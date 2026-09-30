"""Rdzeń agenta ASTRO: kontekst, pętla observe->act->verify, dyspozycja."""

from .. import config
from ..safety import Confirmer
from ..tools import ToolContext, registry as default_registry
from .agent import Agent, AgentResult
from .context import build_context
from .dispatch import DispatchResult, dispatch
from .fast_tools import try_fast
from .session import Session

__all__ = ["Agent", "AgentResult", "build_context", "dispatch", "DispatchResult", "try_fast",
           "create_agent", "Session"]


def create_agent(memory=None, backends=None, registry=None, auto_confirm=False, confirmer=None):
    from ..memory import default_memory

    memory = memory if memory is not None else default_memory()
    reg = registry or default_registry
    try:
        from ..tools import mcp
        mcp.ensure_mcp(reg)
    except Exception:
        pass
    confirmer = confirmer or Confirmer(auto=auto_confirm)
    ctx = ToolContext(settings=config, memory=memory, confirmer=confirmer, registry=reg)
    return Agent(backends=backends, registry=reg, memory=memory, ctx=ctx)
