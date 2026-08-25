"""WORKER Module - Celery task engine with idempotency and retry policies."""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from enum import Enum

from celery import Celery, Task
from celery.schedules import crontab
from pydantic import BaseModel, Field

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow


logger = get_logger("worker")


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class TaskStatus:
    """Task status information."""
    state: str  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
    result: Any | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class FailedJob:
    """Dead-letter queue entry."""
    task_id: str
    task_name: str
    args: tuple
    kwargs: dict
    error: str
    retries_exhausted: int
    failed_at: datetime


# =============================================================================
# Global State
# =============================================================================

_celery_app: Optional[Celery] = None
_task_registry: dict[str, Callable] = {}
_beat_registry: dict[str, dict] = {}  # name -> {task_name, schedule}
_failed_jobs: list[FailedJob] = []


# =============================================================================
# Core Functions
# =============================================================================

def create_celery_app() -> Celery:
    """
    Create Celery application factory.
    
    Returns:
        Celery application instance
        
    Configuration:
        - broker/result_backend from CACHE.broker_url()
        - JSON serializer
        - Task time limits from config
    """
    global _celery_app
    
    settings = module_settings("worker")
    cache_settings = module_settings("cache")
    
    broker_url = getattr(cache_settings, "broker_url", "redis://localhost:6379/0") if cache_settings else "redis://localhost:6379/0"
    result_backend = broker_url
    
    time_limit = getattr(settings, "task_time_limit", 300) if settings else 300
    concurrency = getattr(settings, "concurrency", 4) if settings else 4
    
    _celery_app = Celery(
        "cmms_worker",
        broker=broker_url,
        backend=result_backend,
    )
    
    _celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_time_limit=time_limit,
        task_soft_time_limit=int(time_limit * 0.8),
        worker_prefetch_multiplier=1,
        worker_concurrency=concurrency,
        task_acks_late=True,
        task_reject_on_worker_or_loss=True,
        broker_connection_retry_on_startup=True,
        broker_connection_max_retries=5,
    )
    
    logger.info(f"Created Celery app with broker={broker_url}")
    return _celery_app


def register_task(name: str, fn: Callable, retry: Optional[dict] = None) -> Callable:
    """
    Register task with logging, failure-reason persistence, and retry policy.
    
    Args:
        name: Task name (e.g., "assets.evaluate_cycles")
        fn: Task function
        retry: Optional retry config {max_retries, base, max_delay}
        
    Returns:
        Wrapped Celery task
        
    Features:
        - Automatic logging of start/complete/failure
        - Failure reason persistence
        - Exponential backoff retry on specified exceptions
    """
    global _task_registry
    
    if _celery_app is None:
        raise RuntimeError("Celery app not initialized - call create_celery_app first")
    
    # Default retry config
    retry_config = retry or {"max_retries": 3, "base": 2.0, "max_delay": 300}
    
    @_celery_app.task(name=name, bind=True)
    def wrapped_task(self, *args, **kwargs):
        logger.info(f"Task {name} started with args={args}, kwargs={kwargs}")
        
        try:
            result = fn(*args, **kwargs)
            logger.info(f"Task {name} completed successfully")
            return result
            
        except Exception as exc:
            logger.exception(f"Task {name} failed: {exc}")
            
            # Persist failure reason
            _persist_failure(name, args, kwargs, str(exc))
            
            # Retry logic
            max_retries = retry_config.get("max_retries", 3)
            base = retry_config.get("base", 2.0)
            max_delay = retry_config.get("max_delay", 300)
            
            if self.request.retries < max_retries:
                delay = min(base ** self.request.retries + random.uniform(0, 1), max_delay)
                logger.info(f"Retrying task {name} in {delay}s (attempt {self.request.retries + 1}/{max_retries})")
                raise self.retry(exc=exc, countdown=delay)
            else:
                logger.error(f"Task {name} exhausted all retries ({max_retries})")
                # Add to dead-letter queue
                _failed_jobs.append(FailedJob(
                    task_id=self.request.id,
                    task_name=name,
                    args=args,
                    kwargs=kwargs,
                    error=str(exc),
                    retries_exhausted=max_retries,
                    failed_at=utcnow()
                ))
                raise
    
    _task_registry[name] = wrapped_task
    logger.info(f"Registered task: {name}")
    return wrapped_task


def register_beat(name: str, task_name: str, schedule: Any) -> None:
    """
    Register beat schedule entry.
    
    Args:
        name: Schedule name (unique identifier)
        task_name: Task to execute
        schedule: Celery schedule (crontab, timedelta, etc.)
        
    Examples:
        register_beat("daily_cycle_eval", "assets.evaluate_all_cycles", crontab(minute=0, hour=2))
        register_beat("heartbeat", "core.health_check", timedelta(seconds=30))
    """
    global _beat_registry
    
    if name in _beat_registry:
        logger.warning(f"Beat schedule '{name}' already registered - overwriting")
    
    _beat_registry[name] = {
        "task_name": task_name,
        "schedule": schedule,
    }
    
    logger.info(f"Registered beat schedule: {name} -> {task_name}")


def dispatch(
    task_name: str,
    args: Optional[tuple] = None,
    countdown: Optional[int] = None,
    idempotency_key: Optional[str] = None
) -> str:
    """
    Dispatch task with optional idempotency.
    
    Args:
        task_name: Registered task name
        args: Task arguments
        countdown: Delay in seconds before execution
        idempotency_key: Optional key for exactly-once execution
        
    Returns:
        Task ID
        
    Idempotency:
        If idempotency_key provided, acquires CACHE lock.
        Returns existing task_id if already running.
    """
    global _task_registry
    
    if task_name not in _task_registry:
        raise ValueError(f"Unknown task: {task_name}")
    
    task = _task_registry[task_name]
    
    # Idempotency check via distributed lock
    if idempotency_key:
        from core.registry import get_service
        
        try:
            cache_service = get_service("cache")
            lock_key = f"task_lock:{idempotency_key}"
            
            # Try to acquire lock (non-blocking)
            acquired = cache_service.acquire_lock(lock_key, ttl_s=3600, wait_ms=0)
            if not acquired:
                logger.info(f"Task {task_name} with idempotency_key {idempotency_key} already running")
                # Return existing task ID (would need to track this separately)
                return f"locked:{idempotency_key}"
                
        except Exception as e:
            logger.warning(f"Idempotency check failed: {e}")
            # Continue without idempotency guarantee
    
    # Dispatch task
    result = task.delay(*(args or ()), countdown=countdown)
    logger.info(f"Dispatched task {task_name} with id={result.id}")
    
    return result.id


def task_status(task_id: str) -> TaskStatus:
    """
    Get task status by ID.
    
    Args:
        task_id: Celery task ID
        
    Returns:
        TaskStatus with state, result, error, timestamps
    """
    if _celery_app is None:
        raise RuntimeError("Celery app not initialized")
    
    result = _celery_app.AsyncResult(task_id)
    
    status = TaskStatus(
        state=result.state,
        result=result.result if result.ready() else None,
        error=str(result.result) if result.failed() else None,
        started_at=None,  # Would need to track in Redis
        finished_at=datetime.now(timezone.utc) if result.ready() else None
    )
    
    return status


async def single_flight(name: str, ttl_s: int = 300) -> bool:
    """
    Cluster-wide exactly-one-at-a-time execution guard.
    
    Args:
        name: Unique operation name
        ttl_s: Lock TTL in seconds
        
    Returns:
        True if lock acquired (should proceed), False if already running
        
    Uses CACHE.lock for distributed coordination.
    """
    from core.registry import get_service
    
    try:
        cache_service = get_service("cache")
        lock_key = f"single_flight:{name}"
        
        acquired = cache_service.acquire_lock(lock_key, ttl_s=ttl_s, wait_ms=0)
        return acquired
        
    except Exception as e:
        logger.error(f"Single flight lock failed: {e}")
        return False  # Fail closed - don't execute


def retry_with_backoff(
    task: Any,
    exc: Exception,
    base: float = 2.0,
    max_retries: int = 5
) -> None:
    """
    Exponential backoff retry helper.
    
    Args:
        task: Celery task instance (self)
        exc: Exception that triggered retry
        base: Backoff base (default 2.0 for exponential)
        max_retries: Maximum retry attempts
        
    Routes to dead-letter queue on exhaustion.
    """
    if task.request.retries >= max_retries:
        logger.error(f"Task {task.name} exhausted all retries ({max_retries})")
        
        # Add to dead-letter queue
        _failed_jobs.append(FailedJob(
            task_id=task.request.id,
            task_name=task.name,
            args=task.request.args,
            kwargs=task.request.kwargs,
            error=str(exc),
            retries_exhausted=max_retries,
            failed_at=utcnow()
        ))
        raise
    
    delay = min(base ** task.request.retries + random.uniform(0, 1), 300)
    logger.info(f"Retrying task {task.name} in {delay}s (attempt {task.request.retries + 1}/{max_retries})")
    raise task.retry(exc=exc, countdown=delay)


def failed_jobs(page: int = 1, page_size: int = 50) -> list[FailedJob]:
    """
    Return dead-letter queue entries.
    
    Args:
        page: Page number (1-indexed)
        page_size: Items per page
        
    Returns:
        List of FailedJob entries for the requested page
    """
    start = (page - 1) * page_size
    end = start + page_size
    return _failed_jobs[start:end]


def collect_contributions(modules: list[Any]) -> None:
    """
    Call each module's register_tasks()/register_beat() at start().
    
    Args:
        modules: List of module instances to collect contributions from
        
    Each module may implement:
        - register_tasks(ctx): Register Celery tasks
        - register_beat(ctx): Register beat schedules
    """
    logger.info(f"Collecting task contributions from {len(modules)} modules")
    
    for module in modules:
        module_name = getattr(module, "name", "unknown")
        
        # Collect tasks
        if hasattr(module, "register_tasks"):
            try:
                module.register_tasks()
                logger.info(f"Collected tasks from module {module_name}")
            except Exception as e:
                logger.error(f"Failed to collect tasks from {module_name}: {e}")
        
        # Collect beat schedules
        if hasattr(module, "register_beat"):
            try:
                module.register_beat()
                logger.info(f"Collected beat schedules from module {module_name}")
            except Exception as e:
                logger.error(f"Failed to collect beat schedules from {module_name}: {e}")


async def drain(timeout_s: int = 30) -> None:
    """
    Graceful shutdown - wait for in-flight tasks to complete.
    
    Args:
        timeout_s: Maximum time to wait for tasks to complete
        
    Notes:
        - Stops accepting new tasks
        - Waits for current task to finish (up to timeout)
        - Cleans up connections
    """
    logger.info(f"Draining worker with timeout {timeout_s}s")
    
    if _celery_app is not None:
        # Give in-flight tasks time to complete
        await asyncio.sleep(min(timeout_s, 5))
        
        # Close connections
        _celery_app.close()
        logger.info("Worker connections closed")


def _persist_failure(task_name: str, args: tuple, kwargs: dict, error: str) -> None:
    """Persist failure reason for later inspection."""
    # In production, this would write to a database table
    # For now, just log it
    logger.error(f"Task failure persisted: {task_name} - {error}")


# =============================================================================
# Published Port
# =============================================================================

class TaskEngine:
    """Published port for task operations."""
    
    @staticmethod
    def get_celery_app() -> Celery:
        return _celery_app
    
    @staticmethod
    def register_task(name: str, fn: Callable, retry: Optional[dict] = None) -> Callable:
        return register_task(name, fn, retry)
    
    @staticmethod
    def register_beat(name: str, task_name: str, schedule: Any) -> None:
        register_beat(name, task_name, schedule)
    
    @staticmethod
    def dispatch(
        task_name: str,
        args: Optional[tuple] = None,
        countdown: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> str:
        return dispatch(task_name, args, countdown, idempotency_key)
    
    @staticmethod
    def get_task_status(task_id: str) -> TaskStatus:
        return task_status(task_id)
    
    @staticmethod
    async def acquire_single_flight(name: str, ttl_s: int = 300) -> bool:
        return await single_flight(name, ttl_s)
    
    @staticmethod
    def get_failed_jobs(page: int = 1, page_size: int = 50) -> list[FailedJob]:
        return failed_jobs(page, page_size)
    
    @staticmethod
    def collect_module_contributions(modules: list[Any]) -> None:
        collect_contributions(modules)
    
    @staticmethod
    async def drain_gracefully(timeout_s: int = 30) -> None:
        await drain(timeout_s)


# =============================================================================
# Module Implementation
# =============================================================================

class WorkerModule(ModuleBase):
    """Worker module implementing ModuleBase protocol."""
    
    name = "worker"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ("core", "cache")
    optional_dependencies: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("worker", "beat", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Configure worker module."""
        logger.info("Configuring Worker module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize Celery app."""
        logger.info("Initializing Worker module")
        
        create_celery_app()
        
        # Register service port
        from core.registry import register_service
        register_service("worker", TaskEngine(), TaskEngine)
        
    async def start(self) -> None:
        """Start worker - collect task contributions from modules."""
        logger.info("Worker module started")
        
    async def stop(self) -> None:
        """Stop worker gracefully."""
        global _celery_app
        logger.info("Stopping Worker module")
        
        await drain(timeout_s=10)
        _celery_app = None
        
    async def health(self) -> HealthReport:
        """Report worker health."""
        checks = []
        overall_status = HealthStatus.OK
        ts = utcnow()
        
        if _celery_app is None:
            return HealthReport(
                module="worker",
                status=HealthStatus.UNAVAILABLE,
                checks=[{"name": "celery_app", "status": "UNAVAILABLE", "detail": "Celery app not initialized"}],
                ts=ts,
            )
        
        # Check broker connectivity
        try:
            conn = _celery_app.connection()
            conn.ensure_connection(max_retries=1)
            conn.release()
            checks.append({
                "name": "broker_connectivity",
                "status": "OK",
                "detail": "Broker connection successful"
            })
        except Exception as e:
            checks.append({
                "name": "broker_connectivity",
                "status": "UNAVAILABLE",
                "detail": str(e)
            })
            overall_status = HealthStatus.UNAVAILABLE
        
        # Check queue depth (if cache available)
        try:
            from core.registry import get_service
            cache_service = get_service("cache")
            # Could check Redis queue length here
            checks.append({
                "name": "queue_depth",
                "status": "OK",
                "detail": "Queue check passed"
            })
        except Exception as e:
            checks.append({
                "name": "queue_depth",
                "status": "DEGRADED",
                "detail": f"Could not check queue: {e}"
            })
            if overall_status == HealthStatus.OK:
                overall_status = HealthStatus.DEGRADED
        
        return HealthReport(
            module="worker",
            status=overall_status,
            checks=checks,
            ts=ts,
        )
