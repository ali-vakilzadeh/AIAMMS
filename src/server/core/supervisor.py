"""
Supervisor - Background module health monitoring and degradation propagation.

Runs a background loop that:
1. Polls health of all modules periodically
2. Propagates degradation (if hard dep is UNAVAILABLE, dependent modules become DEGRADED)
3. Applies restart policy per module config
4. Emits module.health_changed events on transitions
"""

import asyncio
from typing import TYPE_CHECKING

from .module_base import HealthStatus
from .health import HealthReport, HealthPoller
from .utils import utcnow

if TYPE_CHECKING:
    from .boot import Application


class Supervisor:
    """
    Background supervisor for module health monitoring.
    
    Attributes:
        app: The booted application
        running: Whether the supervision loop is active
        last_reports: Last known health reports per module
        degradation_map: Which modules are degraded due to dependencies
    """
    
    def __init__(self, app: "Application"):
        self.app = app
        self.running = False
        self._task: asyncio.Task | None = None
        self._poller = HealthPoller(app)
        self._logger = None
        
        # Track last known state
        self.last_reports: dict[str, HealthReport] = {}
        self.degradation_map: dict[str, set[str]] = {}  # module -> set of degraded dependents
    
    def _get_logger(self):
        if self._logger is None:
            import logging
            self._logger = logging.getLogger("core.supervisor")
        return self._logger
    
    async def run(self, interval_s: int = 30) -> None:
        """
        Start the supervision loop.
        
        Args:
            interval_s: Poll interval in seconds (default 30)
        
        Runs in background until stop() is called.
        """
        logger = self._get_logger()
        logger.info(f"Starting supervisor with {interval_s}s interval")
        
        self.running = True
        
        while self.running:
            try:
                await self._iteration()
            except Exception as e:
                logger.error(f"Supervision iteration failed: {e}", exc_info=True)
            
            # Wait for next interval
            await asyncio.sleep(interval_s)
    
    async def _iteration(self) -> None:
        """Single supervision iteration."""
        logger = self._get_logger()
        
        # Poll health
        reports = await self._poller.poll(timeout_s=2.0)
        
        # Detect changes and propagate degradation
        for mod_name, report in reports.items():
            old_report = self.last_reports.get(mod_name)
            
            if old_report is None or old_report.status != report.status:
                # Status changed
                logger.info(
                    f"Module '{mod_name}' status changed: "
                    f"{old_report.status.value if old_report else 'UNKNOWN'} -> {report.status.value}"
                )
                
                # Emit health_changed event
                from .event_bus import get_event_bus
                event_bus = get_event_bus()
                await event_bus.publish(
                    "module.health_changed",
                    {
                        "module": mod_name,
                        "old_status": old_report.status.value if old_report else None,
                        "new_status": report.status.value,
                        "checks": report.checks,
                        "ts": report.ts.isoformat(),
                    }
                )
                
                # Propagate degradation if this module went UNAVAILABLE
                if report.status == HealthStatus.UNAVAILABLE:
                    await self._propagate_degradation(mod_name)
                elif report.status == HealthStatus.OK and old_report:
                    # Module recovered - clear degradation
                    await self._clear_degradation(mod_name)
            
            self.last_reports[mod_name] = report
        
        # Log summary
        ok_count = sum(1 for r in reports.values() if r.status == HealthStatus.OK)
        degraded_count = sum(1 for r in reports.values() if r.status == HealthStatus.DEGRADED)
        unavailable_count = sum(1 for r in reports.values() if r.status == HealthStatus.UNAVAILABLE)
        
        logger.debug(
            f"Health summary: {ok_count} OK, {degraded_count} DEGRADED, {unavailable_count} UNAVAILABLE"
        )
    
    async def _propagate_degradation(self, failed_module: str) -> None:
        """
        Mark modules that depend on the failed module as DEGRADED.
        
        This is a simplified implementation - full version would build
        reverse dependency graph and mark all transitive dependents.
        """
        logger = self._get_logger()
        
        # Find modules that list failed_module as a hard dependency
        degraded_dependents = set()
        
        for mod_name, instance in self.app.started_modules.items():
            if mod_name == failed_module:
                continue
            
            # Check if this module depends on the failed one
            deps = instance.dependencies if hasattr(instance, 'dependencies') else []
            if failed_module in deps:
                degraded_dependents.add(mod_name)
        
        if degraded_dependents:
            logger.warning(
                f"Module '{failed_module}' UNAVAILABLE - marking dependents as DEGRADED: "
                f"{degraded_dependents}"
            )
            self.degradation_map[failed_module] = degraded_dependents
    
    async def _clear_degradation(self, recovered_module: str) -> None:
        """Clear degradation for modules that depended on the recovered module."""
        logger = self._get_logger()
        
        if recovered_module not in self.degradation_map:
            return
        
        recovered_dependents = self.degradation_map.pop(recovered_module)
        logger.info(
            f"Module '{recovered_module}' recovered - clearing degradation for: "
            f"{recovered_dependents}"
        )
    
    def stop(self) -> None:
        """Stop the supervision loop."""
        logger = self._get_logger()
        logger.info("Stopping supervisor...")
        
        self.running = False
        
        if self._task and not self._task.done():
            self._task.cancel()
    
    def get_status(self) -> dict:
        """
        Get current supervision status.
        
        Returns:
            dict with running state and last reports
        """
        return {
            "running": self.running,
            "modules": {
                name: report.to_dict()
                for name, report in self.last_reports.items()
            },
            "degraded": {
                failed: list(deps)
                for failed, deps in self.degradation_map.items()
            },
        }
