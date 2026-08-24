"""Cache Module - Redis services for rate limiting, locks, delayed queues, and KV cache."""

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, AsyncContextManager
from uuid import uuid4

from core.module_base import ModuleBase, ModuleContext, HealthStatus
from core.health import HealthReport
from core.settings import module_settings
from core.logger import get_logger
from core.utils import utcnow

try:
    import redis.asyncio as redis
    from redis.asyncio.lock import Lock as RedisLock
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False


logger = get_logger("cache")


@dataclass
class RateDecision:
    """Result of rate limit check."""
    allowed: bool
    remaining: int
    reset_at: datetime


@dataclass
class DelayedJob:
    """A job scheduled for later execution."""
    job_id: str
    task_name: str
    payload: dict


# Global Redis client
_client: Optional[Any] = None


async def connect() -> Any:
    """Connect to Redis using CMMS_CACHE__URL with retry.
    
    Returns:
        Async Redis client instance
    """
    global _client
    
    if not REDIS_AVAILABLE:
        raise RuntimeError("Redis package not installed. Install with: pip install redis")
    
    settings = module_settings("cache")
    if settings is None:
        raise RuntimeError("Cache settings not loaded")
    
    url = getattr(settings, "url", "redis://localhost:6379")
    
    logger.info(f"Connecting to Redis at {url}")
    
    # Retry logic
    max_retries = 5
    for attempt in range(max_retries):
        try:
            _client = await redis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
            )
            await _client.ping()
            logger.info("Redis connection established")
            return _client
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to connect to Redis after {max_retries} attempts: {e}")
                raise
            wait_time = 2 ** attempt
            logger.warning(f"Redis connection attempt {attempt + 1} failed, retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
    
    raise RuntimeError("Could not connect to Redis")


async def allow(key: str, limit: int, window_s: int) -> RateDecision:
    """Sliding-window rate limiter.
    
    Args:
        key: Rate limit key e.g. 'rl:user:{id}:ai'
        limit: Max calls allowed in window
        window_s: Window size in seconds
        
    Returns:
        RateDecision with allowed status, remaining count, and reset time
    """
    if _client is None:
        raise RuntimeError("Redis not connected - call connect() first")
    
    now = time.time()
    window_start = now - window_s
    
    pipe = _client.pipeline()
    
    # Remove old entries outside the window
    pipe.zremrangebyscore(key, 0, window_start)
    
    # Count current entries
    pipe.zcard(key)
    
    # Add current request
    pipe.zadd(key, {str(uuid4()): now})
    
    # Set expiry on the key
    pipe.expire(key, window_s)
    
    results = await pipe.execute()
    current_count = results[1]
    
    if current_count >= limit:
        # Get the oldest entry to calculate reset time
        oldest = await _client.zrange(key, 0, 0, withscores=True)
        if oldest:
            reset_at = datetime.fromtimestamp(oldest[0][1] + window_s, tz=timezone.utc)
        else:
            reset_at = datetime.fromtimestamp(now + window_s, tz=timezone.utc)
        
        return RateDecision(
            allowed=False,
            remaining=0,
            reset_at=reset_at
        )
    
    return RateDecision(
        allowed=True,
        remaining=limit - current_count - 1,
        reset_at=datetime.fromtimestamp(now + window_s, tz=timezone.utc)
    )


@asynccontextmanager
async def lock(name: str, ttl_s: int, wait_ms: int = 0):
    """Distributed lock using SET NX PX with safe Lua release.
    
    Args:
        name: Lock name
        ttl_s: Auto-release TTL in seconds
        wait_ms: Optional wait time to acquire lock
        
    Yields:
        bool indicating if lock was acquired
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    if not REDIS_AVAILABLE:
        raise RuntimeError("Redis package not installed")
    
    lock_obj = _client.lock(
        f"lock:{name}",
        timeout=ttl_s,
        blocking_timeout=wait_ms / 1000.0 if wait_ms > 0 else 0,
    )
    
    acquired = False
    try:
        acquired = await lock_obj.acquire(blocking=wait_ms > 0)
        yield acquired
    finally:
        if acquired:
            try:
                await lock_obj.release()
            except Exception:
                logger.warning(f"Failed to release lock {name}")


async def delay_schedule(task_name: str, payload: dict, run_at: datetime) -> str:
    """Schedule a delayed job using sorted set.
    
    Args:
        task_name: Worker task name
        payload: Task arguments
        run_at: UTC datetime when job should run
        
    Returns:
        Job ID
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    job_id = str(uuid4())
    score = run_at.timestamp()
    
    job_data = {
        "job_id": job_id,
        "task_name": task_name,
        "payload": payload,
    }
    
    import json
    await _client.zadd("delay_queue", {json.dumps(job_data): score})
    
    logger.debug(f"Scheduled delayed job {job_id} for {run_at}")
    return job_id


async def delay_due(now: Optional[datetime] = None) -> list[DelayedJob]:
    """Atomically pop all due jobs from the delay queue.
    
    Args:
        now: Current UTC time (defaults to now)
        
    Returns:
        List of DelayedJob ready for execution
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    if now is None:
        now = utcnow()
    
    score = now.timestamp()
    import json
    
    # Atomically pop due jobs
    jobs = []
    while True:
        result = await _client.zpopmin("delay_queue", count=10)
        if not result:
            break
            
        for item, job_score in result:
            if job_score > score:
                # Put it back and stop
                await _client.zadd("delay_queue", {item: job_score})
                break
            
            job_data = json.loads(item)
            jobs.append(DelayedJob(
                job_id=job_data["job_id"],
                task_name=job_data["task_name"],
                payload=job_data["payload"],
            ))
    
    return jobs


async def kv_get(key: str) -> Optional[str]:
    """Get value from Redis KV store.
    
    Args:
        key: Cache key
        
    Returns:
        Value or None if not found
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    return await _client.get(key)


async def kv_set(key: str, value: str, ttl_s: Optional[int] = None) -> None:
    """Set value in Redis KV store with optional TTL.
    
    Args:
        key: Cache key
        value: Value to store
        ttl_s: Optional expiry in seconds
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    if ttl_s:
        await _client.setex(key, ttl_s, value)
    else:
        await _client.set(key, value)


async def kv_delete(key: str) -> None:
    """Delete key from Redis KV store.
    
    Args:
        key: Cache key
    """
    if _client is None:
        raise RuntimeError("Redis not connected")
    
    await _client.delete(key)


def broker_url() -> str:
    """Return Redis URL for Celery broker.
    
    Returns:
        Redis URL string
    """
    settings = module_settings("cache")
    if settings is None:
        raise RuntimeError("Cache settings not loaded")
    
    return getattr(settings, "url", "redis://localhost:6379")


async def health_check() -> HealthReport:
    """Check Redis connectivity, latency, and memory.
    
    Returns:
        HealthReport with status OK/DEGRADED/UNAVAILABLE
    """
    checks = []
    overall_status = HealthStatus.OK
    ts = utcnow()
    
    if _client is None:
        return HealthReport(
            module="cache",
            status=HealthStatus.UNAVAILABLE,
            checks=[{"name": "connection", "status": "UNAVAILABLE", "detail": "Not connected"}],
            ts=ts,
        )
    
    # Check connectivity and latency
    try:
        start = time.time()
        await _client.ping()
        latency_ms = (time.time() - start) * 1000
        
        checks.append({
            "name": "connectivity",
            "status": "OK",
            "latency_ms": round(latency_ms, 2),
            "detail": f"PING successful ({latency_ms:.2f}ms)"
        })
        
        # Degraded if latency > 100ms
        if latency_ms > 100:
            overall_status = HealthStatus.DEGRADED
            
    except Exception as e:
        checks.append({
            "name": "connectivity",
            "status": "UNAVAILABLE",
            "detail": str(e)
        })
        overall_status = HealthStatus.UNAVAILABLE
    
    # Check memory usage
    try:
        info = await _client.info("memory")
        used_memory = info.get("used_memory_human", "unknown")
        checks.append({
            "name": "memory",
            "status": "OK",
            "detail": f"Used: {used_memory}"
        })
    except Exception as e:
        checks.append({
            "name": "memory",
            "status": "DEGRADED",
            "detail": f"Could not fetch: {e}"
        })
        if overall_status == HealthStatus.OK:
            overall_status = HealthStatus.DEGRADED
    
    return HealthReport(
        module="cache",
        status=overall_status,
        checks=checks,
        ts=ts,
    )


class CacheService:
    """Published port for cache operations."""
    
    @staticmethod
    async def get_client():
        return _client
    
    @staticmethod
    async def allow_rate_limit(key: str, limit: int, window_s: int) -> RateDecision:
        return await allow(key, limit, window_s)
    
    @staticmethod
    async def acquire_lock(name: str, ttl_s: int, wait_ms: int = 0):
        return lock(name, ttl_s, wait_ms)
    
    @staticmethod
    async def schedule_delay(task_name: str, payload: dict, run_at: datetime) -> str:
        return await delay_schedule(task_name, payload, run_at)
    
    @staticmethod
    async def get_due_jobs(now: Optional[datetime] = None) -> list[DelayedJob]:
        return await delay_due(now)
    
    @staticmethod
    async def kv_get(key: str) -> Optional[str]:
        return await kv_get(key)
    
    @staticmethod
    async def kv_set(key: str, value: str, ttl_s: Optional[int] = None) -> None:
        await kv_set(key, value, ttl_s)
    
    @staticmethod
    async def kv_delete(key: str) -> None:
        await kv_delete(key)
    
    @staticmethod
    def get_broker_url() -> str:
        return broker_url()
    
    @staticmethod
    async def check_health() -> HealthReport:
        return await health_check()


class CacheModule(ModuleBase):
    """Cache module implementing ModuleBase protocol."""
    
    name = "cache"
    version = "1.0.0"
    dependencies: tuple[str, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ("api", "worker", "beat", "mcp", "all-in-one")
    
    async def configure(self, settings: Any) -> None:
        """Validate cache configuration."""
        logger.info("Configuring Cache module")
        
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize Redis connection."""
        logger.info("Initializing Cache module")
        await connect()
        
        # Register service port
        from core.registry import register_service
        register_service("cache", CacheService(), CacheService)
        
    async def start(self) -> None:
        """Start Cache module."""
        logger.info("Cache module started")
        
    async def stop(self) -> None:
        """Stop Cache module - close connection."""
        global _client
        logger.info("Stopping Cache module")
        if _client is not None:
            await _client.close()
            _client = None
        
    async def health(self) -> HealthReport:
        """Report cache health."""
        return await health_check()
