"""
CMMS SaaS Server - Core Microkernel

This module provides the microkernel that discovers, validates, boots, and supervises all modules.
ZERO CMMS business logic lives here.
"""

from .module_base import ModuleBase, ModuleMeta
from .registry import ServiceRegistry, get_registry
from .event_bus import EventBus, get_event_bus
from .settings import SettingsLoader, SettingsBundle, module_settings
from .dependency import DependencyGraphValidator, DependencyCycleError, UnknownDependencyError
from .boot import BootOrchestrator, Application
from .health import HealthPoller, HealthReport, HealthStatus
from .supervisor import Supervisor
from .utils import utcnow, new_id, new_request_id
from .logger import get_logger, setup_structured_logging
from .feature_flags import feature_enabled

__all__ = [
    # Core types
    "ModuleBase",
    "ModuleMeta",
    "Application",
    "HealthReport",
    "HealthStatus",
    "SettingsBundle",
    # Errors
    "DependencyCycleError",
    "UnknownDependencyError",
    # Functions
    "discover_modules",
    "validate_dependency_graph",
    "topological_order",
    "boot",
    "shutdown",
    "register_service",
    "get_service",
    "publish",
    "subscribe",
    "load_settings",
    "module_settings",
    "get_logger",
    "utcnow",
    "new_id",
    "new_request_id",
    "poll_health",
    "supervise",
    "feature_enabled",
]

# Lazy-initialized singletons
_registry: ServiceRegistry | None = None
_event_bus: EventBus | None = None
_settings: SettingsBundle | None = None
_application: Application | None = None


def _get_or_init_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


def _get_or_init_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def discover_modules(package_root: str = "modules") -> list[ModuleMeta]:
    """
    CORE-01: Import every subpackage, collect classes subclassing ModuleBase,
    return their metadata. Duplicate module names raise.
    """
    from .discovery import discover_modules as _discover
    return _discover(package_root)


def validate_dependency_graph(modules: list[ModuleMeta]) -> None:
    """
    CORE-02: Verify all declared dependencies exist and the graph is acyclic.
    Raise DependencyCycleError(cycle_path) or UnknownDependencyError.
    """
    validator = DependencyGraphValidator()
    validator.validate(modules)


def topological_order(modules: list[ModuleMeta]) -> list[str]:
    """
    CORE-03: Kahn's algorithm; deterministic alphabetical tie-break.
    Returns list of module names in start order.
    """
    return topological_sort(modules)


def boot(profile: str) -> Application:
    """
    CORE-04: Load settings, init logging, discover -> validate -> sort -> filter modules
    whose profiles include this profile, then run configure() -> initialize(ctx) -> start() in order.
    Log each module name+version.
    
    Profile can be: api | worker | beat | mcp | all-in-one
    """
    global _application, _registry, _event_bus, _settings
    
    orchestrator = BootOrchestrator()
    _application = orchestrator.boot(profile)
    _registry = _application.registry
    _event_bus = _application.event_bus
    _settings = _application.settings
    
    # Start supervision loop
    supervisor = Supervisor(_application)
    _application.supervisor = supervisor
    
    return _application


def shutdown(app: Application) -> None:
    """
    CORE-05: Stop modules in reverse topological order; each module drains in-flight work;
    close pools; flush logs. Non-zero exit if any module failed to stop.
    """
    if app.supervisor:
        app.supervisor.stop()
    
    orchestrator = BootOrchestrator()
    orchestrator.shutdown(app)


def register_service(name: str, port, interface: type) -> None:
    """
    CORE-06: Publish a typed port to the registry.
    Raise on duplicate name or interface mismatch.
    """
    registry = _get_or_init_registry()
    registry.register_service(name, port, interface)


def get_service(name: str, interface: type):
    """
    CORE-07: Lookup + type check.
    Raise ServiceNotRegistered / InterfaceMismatch.
    This is the ONLY cross-module call mechanism.
    """
    registry = _get_or_init_registry()
    return registry.get_service(name, interface)


async def publish(event: str, payload: dict, post_commit: bool = False) -> None:
    """
    CORE-08: Dispatch to all subscribers.
    Each subscriber runs in isolated try/except; a failing listener never breaks the publisher or other listeners.
    """
    event_bus = _get_or_init_event_bus()
    await event_bus.publish(event, payload, post_commit)


def subscribe(event: str, handler, post_commit: bool = False) -> None:
    """
    CORE-09: Register listener.
    Wildcard '*' used by AUDIT. Raise on duplicate (event, handler) pair.
    """
    event_bus = _get_or_init_event_bus()
    event_bus.subscribe(event, handler, post_commit)


def load_settings() -> SettingsBundle:
    """
    CORE-10: Parse env vars CMMS_<MODULE>__<KEY>; validate each module's pydantic Settings;
    fail boot with field-level error list on invalid config. Secrets never logged.
    """
    global _settings
    loader = SettingsLoader()
    _settings = loader.load_settings()
    return _settings


def get_logger(name: str):
    """
    CORE-12: Structured JSON logger with field module=name.
    Namespaced logging; request_id correlation injected by API middleware.
    """
    return get_logger(name)


def poll_health(timeout_s: float = 2.0) -> dict[str, HealthReport]:
    """
    CORE-14: Call every started module's health() concurrently;
    timed-out modules reported UNAVAILABLE.
    """
    if _application is None:
        raise RuntimeError("Application not booted. Call boot() first.")
    
    poller = HealthPoller(_application)
    import asyncio
    return asyncio.run(poller.poll(timeout_s))


async def supervise(interval_s: int = 30) -> None:
    """
    CORE-15: Background loop: poll_health -> propagate degradation
    (dependent modules become DEGRADED if a hard dep is UNAVAILABLE) ->
    apply restart policy per module config -> emit module.health_changed on transitions.
    """
    if _application is None:
        raise RuntimeError("Application not booted. Call boot() first.")
    
    supervisor = Supervisor(_application)
    await supervisor.run(interval_s)
