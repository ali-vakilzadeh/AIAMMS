"""
Health Poller - Concurrent module health checking.

Polls all started modules' health() methods concurrently.
Times out slow modules and reports them as UNAVAILABLE.
"""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from .module_base import HealthStatus
from .utils import utcnow

if TYPE_CHECKING:
    from .boot import Application


class HealthReport:
    """
    Health report for a single module.
    
    Attributes:
        module: Module name
        status: Overall health status (OK, DEGRADED, UNAVAILABLE)
        checks: List of individual check results
        ts: Timestamp of the check
        latency_ms: Total time to complete health check
    """
    
    def __init__(
        self,
        module: str,
        status: HealthStatus = HealthStatus.OK,
        checks: list[dict] | None = None,
        ts: datetime | None = None,
        latency_ms: float = 0.0,
    ):
        self.module = module
        self.status = status
        self.checks = checks or []
        self.ts = ts or utcnow()
        self.latency_ms = latency_ms
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "module": self.module,
            "status": self.status.value,
            "checks": self.checks,
            "ts": self.ts.isoformat(),
            "latency_ms": self.latency_ms,
        }
    
    @classmethod
    def unavailable(cls, module: str, reason: str) -> "HealthReport":
        """Create an UNAVAILABLE report with a reason."""
        return cls(
            module=module,
            status=HealthStatus.UNAVAILABLE,
            checks=[{
                "name": "health_check",
                "status": HealthStatus.UNAVAILABLE.value,
                "detail": reason,
                "latency_ms": 0,
            }],
        )
    
    @classmethod
    def degraded(cls, module: str, checks: list[dict]) -> "HealthReport":
        """Create a DEGRADED report with check details."""
        return cls(
            module=module,
            status=HealthStatus.DEGRADED,
            checks=checks,
        )


class HealthPoller:
    """
    Poll health of all modules in the application.
    
    Calls each module's health() method concurrently with timeout.
    Aggregates results into per-module HealthReport objects.
    """
    
    def __init__(self, app: "Application"):
        self.app = app
        self._logger = None
    
    def _get_logger(self):
        if self._logger is None:
            import logging
            self._logger = logging.getLogger("core.health")
        return self._logger
    
    async def poll(self, timeout_s: float = 2.0) -> dict[str, HealthReport]:
        """
        Poll all started modules concurrently.
        
        Args:
            timeout_s: Per-module timeout in seconds (default 2.0)
        
        Returns:
            dict mapping module name -> HealthReport
        
        Modules that timeout are reported as UNAVAILABLE.
        """
        logger = self._get_logger()
        start_time = utcnow()
        
        # Get all started modules from registry
        started_modules = list(self.app.started_modules.values())
        
        if not started_modules:
            return {}
        
        # Create health check tasks
        async def check_module(module) -> tuple[str, HealthReport]:
            mod_name = module.name
            try:
                # Run health check with timeout
                async with asyncio.timeout(timeout_s):
                    result = await module.health()
                    
                    # Parse result into HealthReport
                    if isinstance(result, HealthReport):
                        return (mod_name, result)
                    elif isinstance(result, dict):
                        status_str = result.get("status", "OK")
                        status = HealthStatus(status_str)
                        return (mod_name, HealthReport(
                            module=mod_name,
                            status=status,
                            checks=result.get("checks", []),
                            ts=utcnow(),
                        ))
                    else:
                        # Assume OK if just returns something truthy
                        return (mod_name, HealthReport(module=mod_name))
            
            except asyncio.TimeoutError:
                logger.warning(f"Module '{mod_name}' health check timed out after {timeout_s}s")
                return (mod_name, HealthReport.unavailable(
                    mod_name,
                    f"Health check timed out after {timeout_s}s"
                ))
            except Exception as e:
                logger.error(f"Module '{mod_name}' health check failed: {e}", exc_info=True)
                return (mod_name, HealthReport.unavailable(
                    mod_name,
                    str(e)
                ))
        
        # Run all checks concurrently
        tasks = [check_module(mod) for mod in started_modules]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build result dict
        reports: dict[str, HealthReport] = {}
        for result in results:
            if isinstance(result, Exception):
                # Unexpected error in gather
                logger.error(f"Unexpected health check error: {result}", exc_info=True)
                continue
            
            mod_name, report = result
            reports[mod_name] = report
        
        # Log summary
        ok_count = sum(1 for r in reports.values() if r.status == HealthStatus.OK)
        total = len(reports)
        logger.info(f"Health poll complete: {ok_count}/{total} modules healthy")
        
        return reports
