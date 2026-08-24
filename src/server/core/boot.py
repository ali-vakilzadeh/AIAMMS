"""
Boot Orchestrator - Module discovery, validation, and lifecycle orchestration.

Coordinates the boot sequence:
1. Load settings
2. Initialize logging
3. Discover modules
4. Validate dependency graph
5. Topological sort
6. Filter by profile
7. Run configure() -> initialize(ctx) -> start() in order

Also handles graceful shutdown in reverse order.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from .module_base import ModuleBase, ModuleMeta, ModuleContext, HealthStatus
from .settings import SettingsBundle, SettingsLoader, register_settings
from .dependency import validate_dependency_graph, topological_sort
from .registry import ServiceRegistry
from .event_bus import EventBus
from .logger import setup_structured_logging, get_logger
from .utils import utcnow, new_request_id

if TYPE_CHECKING:
    from .supervisor import Supervisor


@dataclass
class Application:
    """
    The booted application instance.
    
    Attributes:
        registry: Service registry for cross-module communication
        event_bus: Event bus for pub/sub messaging
        settings: Validated settings bundle
        started_modules: Map of module name -> started instance
        profile: The profile this app was booted with
        supervisor: Background supervision loop (set after boot)
    """
    registry: ServiceRegistry
    event_bus: EventBus
    settings: SettingsBundle
    started_modules: dict[str, ModuleBase] = field(default_factory=dict)
    profile: str = "all-in-one"
    supervisor: "Supervisor | None" = None


class BootOrchestrator:
    """
    Orchestrates the module boot sequence.
    
    Boot order:
    1. load_settings() - Parse env vars
    2. setup_structured_logging() - Initialize logging
    3. discover_modules() - Find all ModuleBase subclasses
    4. validate_dependency_graph() - Check for cycles/unknown deps
    5. topological_order() - Sort modules
    6. Filter by profile (api|worker|beat|mcp|all-in-one)
    7. For each module in order:
       a. configure(settings)
       b. initialize(ctx)
       c. start()
    """
    
    def __init__(self):
        self._logger = None
    
    def _get_logger(self):
        if self._logger is None:
            self._logger = get_logger("boot")
        return self._logger
    
    def boot(self, profile: str) -> Application:
        """
        Boot the application with the given profile.
        
        Args:
            profile: One of 'api', 'worker', 'beat', 'mcp', 'all-in-one'
        
        Returns:
            Application: The fully booted application
        
        Raises:
            DependencyCycleError: If module dependencies form a cycle
            UnknownDependencyError: If a module depends on unknown module
            SettingsLoadError: If settings validation fails
        """
        logger = self._get_logger()
        logger.info(f"Booting CMMS server with profile: {profile}")
        
        # Step 1: Load settings
        logger.info("Loading settings...")
        loader = SettingsLoader()
        settings = loader.load_settings()
        
        # Step 2: Initialize logging
        logger.info("Initializing structured logging...")
        setup_structured_logging()
        
        # Step 3: Discover modules
        logger.info("Discovering modules...")
        from .discovery import discover_modules
        all_modules = discover_modules("modules")
        logger.info(f"Discovered {len(all_modules)} modules: {[m.name for m in all_modules]}")
        
        if not all_modules:
            logger.warning("No modules discovered. Continuing with empty module set.")
        
        # Step 4: Validate dependency graph
        logger.info("Validating dependency graph...")
        validate_dependency_graph(all_modules)
        
        # Step 5: Topological sort
        logger.info("Computing topological order...")
        sorted_names = topological_sort(all_modules)
        modules_by_name = {m.name: m for m in all_modules}
        sorted_modules = [modules_by_name[name] for name in sorted_names]
        logger.info(f"Boot order: {sorted_names}")
        
        # Step 6: Filter by profile
        logger.info(f"Filtering modules for profile: {profile}")
        filtered_modules = []
        for mod_meta in sorted_modules:
            # Module runs if its profiles include this profile or 'all-in-one'
            if profile in mod_meta.profiles or "all-in-one" in mod_meta.profiles:
                filtered_modules.append(mod_meta)
            else:
                logger.debug(f"Skipping module '{mod_meta.name}' - not in profile '{profile}'")
        
        logger.info(f"Modules for profile '{profile}': {[m.name for m in filtered_modules]}")
        
        # Step 7: Instantiate and boot modules
        logger.info("Starting modules...")
        registry = ServiceRegistry()
        event_bus = EventBus()
        started_modules: dict[str, ModuleBase] = {}
        
        # Create platform-level context (no org/user yet)
        platform_ctx = ModuleContext(
            request_id=new_request_id(),
        )
        
        for mod_meta in filtered_modules:
            mod_name = mod_meta.name
            logger.info(f"Booting module '{mod_name}' v{mod_meta.version}...")
            
            try:
                # Import the module class
                mod_class = self._load_module_class(mod_meta)
                
                # Instantiate
                instance = mod_class()
                
                # Get settings for this module
                mod_settings = settings.get_module(mod_name.upper())
                
                # Configure
                logger.debug(f"Configuring module '{mod_name}'...")
                asyncio.run(instance.configure(mod_settings))
                
                # Initialize
                logger.debug(f"Initializing module '{mod_name}'...")
                asyncio.run(instance.initialize(platform_ctx))
                
                # Start
                logger.debug(f"Starting module '{mod_name}'...")
                asyncio.run(instance.start())
                
                started_modules[mod_name] = instance
                logger.info(f"Module '{mod_name}' started successfully")
            
            except Exception as e:
                logger.error(f"Failed to boot module '{mod_name}': {e}", exc_info=True)
                # Shutdown already-started modules
                self._shutdown_partial(started_modules, registry, event_bus)
                raise RuntimeError(f"Module '{mod_name}' failed to boot: {e}") from e
        
        logger.info(f"All {len(started_modules)} modules booted successfully")
        
        return Application(
            registry=registry,
            event_bus=event_bus,
            settings=settings,
            started_modules=started_modules,
            profile=profile,
        )
    
    def _load_module_class(self, meta: ModuleMeta) -> type[ModuleBase]:
        """
        Load the ModuleBase subclass for a module metadata.
        
        This uses naming convention: module 'db' is in 'modules.db' package
        with class 'DbModule'.
        """
        # Try common naming patterns
        patterns = [
            f"src.server.modules.{meta.name}.{meta.name.capitalize()}Module",
            f"src.server.modules.{meta.name}.module",
            f"modules.{meta.name}.{meta.name.capitalize()}Module",
        ]
        
        for pattern in patterns:
            try:
                parts = pattern.rsplit('.', 1)
                if len(parts) != 2:
                    continue
                mod_path, class_name = parts
                mod = __import__(mod_path, fromlist=[class_name])
                cls = getattr(mod, class_name, None)
                if cls and issubclass(cls, ModuleBase):
                    return cls
            except (ImportError, AttributeError):
                continue
        
        # Fallback: scan for any ModuleBase subclass in the module
        try:
            mod = __import__(f"src.server.modules.{meta.name}", fromlist=[''])
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, ModuleBase)
                    and attr is not ModuleBase
                ):
                    return attr
        except ImportError:
            pass
        
        raise ImportError(f"Could not find ModuleBase subclass for module '{meta.name}'")
    
    def _shutdown_partial(
        self,
        started: dict[str, ModuleBase],
        registry: ServiceRegistry,
        event_bus: EventBus,
    ) -> None:
        """Shutdown modules that were already started when a later module fails."""
        logger = self._get_logger()
        logger.warning("Shutting down partially booted application...")
        
        # Reverse order
        for name in reversed(list(started.keys())):
            try:
                asyncio.run(started[name].stop())
                logger.info(f"Module '{name}' stopped")
            except Exception as e:
                logger.error(f"Error stopping module '{name}': {e}", exc_info=True)
    
    def shutdown(self, app: Application) -> None:
        """
        Gracefully shutdown the application.
        
        Stops modules in reverse topological order.
        Each module drains in-flight work before stopping.
        """
        logger = self._get_logger()
        logger.info("Shutting down application...")
        
        # Get module names in current order, then reverse
        module_order = list(app.started_modules.keys())
        
        for name in reversed(module_order):
            instance = app.started_modules[name]
            logger.info(f"Stopping module '{name}'...")
            
            try:
                asyncio.run(instance.stop())
                logger.info(f"Module '{name}' stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping module '{name}': {e}", exc_info=True)
        
        logger.info("Application shutdown complete")
