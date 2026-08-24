"""
ModuleBase - Abstract base class for all CMMS modules.

Every module must subclass ModuleBase and implement its lifecycle methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class HealthStatus(str, Enum):
    """Module health status."""
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ModuleMeta:
    """Metadata extracted from a ModuleBase subclass."""
    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)  # api, worker, beat, mcp, all-in-one


class ModuleContext:
    """
    Context passed to modules during initialization.
    
    Attributes:
        org_id: Current organization ID (may be None for platform-level ops)
        user_id: Current user ID (may be None for system ops)
        role: Current role (may be None for system ops)
        request_id: Request correlation ID
        timezone: User timezone (may be None)
    """
    def __init__(
        self,
        org_id: Any | None = None,
        user_id: Any | None = None,
        role: str | None = None,
        request_id: str | None = None,
        timezone: str | None = None,
    ):
        self.org_id = org_id
        self.user_id = user_id
        self.role = role
        self.request_id = request_id
        self.timezone = timezone


class ModuleBase(ABC):
    """
    Abstract base class for all CMMS modules.
    
    Lifecycle:
        1. Class is discovered by core.discover_modules()
        2. configure() is called with module-specific settings
        3. initialize(ctx) is called with a ModuleContext
        4. start() is called to begin accepting work
        5. health() is polled periodically
        6. stop() is called on shutdown
    
    A module may only import modules from earlier waves or same wave with lower priority.
    Never import a later module.
    """
    
    # Class-level metadata - override in subclasses
    name: str = ""
    version: str = "0.0.0"
    dependencies: list[str] = []
    optional_dependencies: list[str] = []
    profiles: list[str] = ["all-in-one"]  # Which profiles this module runs in
    
    @abstractmethod
    async def configure(self, settings: Any) -> None:
        """
        Configure the module with validated settings.
        
        Called during boot before initialize(). Use this to:
        - Store settings for later use
        - Validate cross-setting constraints
        - Prepare configuration-dependent resources
        
        Args:
            settings: This module's pydantic Settings object from core.module_settings(name)
        """
        pass
    
    @abstractmethod
    async def initialize(self, ctx: ModuleContext) -> None:
        """
        Initialize the module's resources.
        
        Called after configure() and before start(). Use this to:
        - Create database tables / run migrations
        - Initialize connection pools
        - Set up caches
        - Register event listeners
        
        Args:
            ctx: ModuleContext with platform-level context
        """
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """
        Start the module's background tasks and make it ready for work.
        
        Called after initialize(). Use this to:
        - Start background loops
        - Register Celery tasks
        - Mount API routers
        - Begin processing
        
        This should be fast and non-blocking. Long-running work goes in background tasks.
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """
        Stop the module gracefully.
        
        Called during shutdown in reverse topological order. Use this to:
        - Drain in-flight work
        - Close connections
        - Cancel background tasks
        - Flush logs
        
        Should complete within timeout (default 30s) or be forcefully terminated.
        """
        pass
    
    @abstractmethod
    async def health(self) -> dict:
        """
        Report module health.
        
        Called periodically by the supervisor. Return quickly (<2s).
        
        Returns:
            dict with:
                - status: HealthStatus (OK, DEGRADED, UNAVAILABLE)
                - checks: list of {name, status, latency_ms, detail}
                - ts: datetime of check
        
        Examples:
            - DB module: check pool saturation, ping database
            - Cache module: PING redis, check memory
            - Worker module: check queue depth, task failure rate
        """
        pass
    
    @classmethod
    def get_meta(cls) -> ModuleMeta:
        """Extract metadata from this module class."""
        return ModuleMeta(
            name=cls.name,
            version=cls.version,
            dependencies=cls.dependencies.copy(),
            optional_dependencies=cls.optional_dependencies.copy(),
            profiles=cls.profiles.copy(),
        )
