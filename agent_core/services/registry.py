import logging
from typing import Any, Dict, Protocol, Type, TypeVar, Optional

logger = logging.getLogger("agent_core.registry")

T = TypeVar("T")

class ICapability(Protocol):
    """Base protocol for any capability."""
    async def health(self) -> bool: ...


class ICodeExecution(ICapability, Protocol):
    """Capability for executing code or terminal commands."""
    async def execute(self, command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...


class IDeepResearch(ICapability, Protocol):
    """Capability for long-horizon deep research tasks."""
    async def research(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...


class IPersona(ICapability, Protocol):
    """Capability for adopting a persona and retrieving semantic memory."""
    async def get_context(self, target_id: str) -> str: ...
    async def list_personas(self) -> Any: ...


class IVision(ICapability, Protocol):
    """Capability for visual GUI interaction and reasoning."""
    async def run_visual_task(self, target_url: str, task: str) -> Dict[str, Any]: ...


class CapabilityRegistry:
    """Central registry for all agent capabilities.

    Instead of hardcoding services (e.g., self.az = AgentZeroClient),
    we register capabilities (e.g., registry.register(ICodeExecution, agent_zero_client)).
    """
    def __init__(self):
        self._capabilities: Dict[Type, Any] = {}

    def register(self, protocol: Type[T], implementation: T) -> None:
        """Register an implementation for a specific capability protocol."""
        self._capabilities[protocol] = implementation
        logger.debug(f"Registered capability: {protocol.__name__} -> {implementation.__class__.__name__}")

    def get(self, protocol: Type[T]) -> Optional[T]:
        """Retrieve an implementation for a specific capability protocol."""
        return self._capabilities.get(protocol)

    def has(self, protocol: Type[T]) -> bool:
        """Check if a capability is registered."""
        return protocol in self._capabilities
