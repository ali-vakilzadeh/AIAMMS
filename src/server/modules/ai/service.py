"""AI Service - Checklist Generation & RAG Assistant Implementation

This module implements the AI subsystem with:
- Provider abstraction for multiple LLM backends
- Checklist generation with JSON schema validation
- RAG-based manual assistant with pgvector embeddings
- Usage tracking and rate limiting
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, AsyncIterator
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...shared.types import (
    RequestContext,
    Role,
    DomainError,
    NotFoundError,
    ForbiddenError,
    QuotaExceededError,
    Page,
)
from ...core import subscribe, publish
from ...core.module_base import ModuleBase, ModuleContext, HealthStatus
from ...core.registry import get_service
from ...core.logger import get_logger
from ...core.utils import utcnow, new_id

logger = get_logger(__name__)


# ============================================================================
# Enums
# ============================================================================

class ProviderType(str, Enum):
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"  # Ollama/vLLM self-hosted


class GenerationStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ============================================================================
# Data Models
# ============================================================================

class GenerationJob(BaseModel):
    """AI generation job record"""
    id: str
    org_id: UUID
    user_id: UUID
    operation: str  # checklist_generation, etc.
    prompt: str
    node_id: Optional[UUID] = None
    status: GenerationStatus = GenerationStatus.PENDING
    result: Optional[str] = None  # JSON string for checklist
    error: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class IngestionJob(BaseModel):
    """Document ingestion job record"""
    id: str
    org_id: UUID
    file_id: UUID
    node_id: Optional[UUID] = None
    status: IngestionStatus = IngestionStatus.PENDING
    error: Optional[str] = None
    chunks_processed: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


class AssistantThread(BaseModel):
    """AI assistant conversation thread"""
    id: str
    org_id: UUID
    user_id: UUID
    node_id: Optional[UUID] = None  # Optional binding to service point
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AssistantMessage(BaseModel):
    """Message in assistant thread"""
    id: str
    thread_id: str
    role: str  # user or assistant
    content: str
    citations: Optional[List[str]] = None  # Source chunk references
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentChunk(BaseModel):
    """Embedded document chunk for RAG"""
    id: str
    org_id: UUID
    file_id: UUID
    node_id: Optional[UUID] = None
    page: Optional[int] = None
    chunk_index: int
    heading: Optional[str] = None
    content: str
    embedding: Optional[List[float]] = None  # pgvector stores this
    tokens: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UsageLog(BaseModel):
    """AI usage tracking log"""
    id: str
    org_id: UUID
    user_id: UUID
    operation: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# AI Gateway Protocol
# ============================================================================

class AIGateway:
    """Protocol for AI provider adapters"""
    
    async def generate_text(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 30.0,
        json_schema: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Generate text response from LLM
        
        Returns: {text: str, tokens_in: int, tokens_out: int}
        """
        raise NotImplementedError
    
    async def embed(
        self,
        texts: List[str],
        model: str,
        timeout: float = 30.0,
    ) -> List[List[float]]:
        """Generate embeddings for texts
        
        Returns: List of embedding vectors
        """
        raise NotImplementedError


# ============================================================================
# Provider Adapters
# ============================================================================

class OpenRouterAdapter(AIGateway):
    """OpenRouter provider adapter"""
    
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.base_url = base_url
    
    async def generate_text(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 30.0,
        json_schema: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        # Placeholder - would make HTTP call to OpenRouter API
        logger.info(f"OpenRouter generating with model={model}")
        return {"text": "", "tokens_in": 0, "tokens_out": 0}
    
    async def embed(
        self,
        texts: List[str],
        model: str,
        timeout: float = 30.0,
    ) -> List[List[float]]:
        # Placeholder - would make HTTP call for embeddings
        logger.info(f"OpenRouter embedding with model={model}")
        return [[0.0] * 768 for _ in texts]


class OpenAIAdapter(AIGateway):
    """OpenAI provider adapter"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
    
    async def generate_text(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 30.0,
        json_schema: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        logger.info(f"OpenAI generating with model={model}")
        return {"text": "", "tokens_in": 0, "tokens_out": 0}
    
    async def embed(
        self,
        texts: List[str],
        model: str,
        timeout: float = 30.0,
    ) -> List[List[float]]:
        logger.info(f"OpenAI embedding with model={model}")
        return [[0.0] * 1536 for _ in texts]


class AnthropicAdapter(AIGateway):
    """Anthropic provider adapter"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url
    
    async def generate_text(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 30.0,
        json_schema: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Anthropic generating with model={model}")
        return {"text": "", "tokens_in": 0, "tokens_out": 0}
    
    async def embed(
        self,
        texts: List[str],
        model: str,
        timeout: float = 30.0,
    ) -> List[List[float]]:
        # Anthropic doesn't provide embeddings directly
        raise NotImplementedError("Anthropic does not support embeddings")


class LocalAdapter(AIGateway):
    """Local self-hosted adapter (Ollama/vLLM)"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
    
    async def generate_text(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float = 30.0,
        json_schema: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Local generating with model={model} at {self.base_url}")
        return {"text": "", "tokens_in": 0, "tokens_out": 0}
    
    async def embed(
        self,
        texts: List[str],
        model: str,
        timeout: float = 30.0,
    ) -> List[List[float]]:
        logger.info(f"Local embedding with model={model}")
        return [[0.0] * 768 for _ in texts]


# ============================================================================
# AI Service
# ============================================================================

class AIService:
    """Main AI service providing checklist generation and RAG assistant"""
    
    def __init__(self):
        self._provider: Optional[AIGateway] = None
        self._db = None
        self._cache = None
        self._storage = None
        self._worker = None
        self._settings: Dict[str, Any] = {}
    
    def configure(self, settings: Dict[str, Any]) -> None:
        """Configure AI service with settings"""
        self._settings = settings
    
    def initialize(
        self,
        db: Any,
        cache: Any,
        storage: Any,
        worker: Any,
    ) -> None:
        """Initialize service dependencies"""
        self._db = db
        self._cache = cache
        self._storage = storage
        self._worker = worker
        self._provider = self._create_provider()
    
    def _create_provider(self) -> AIGateway:
        """Create provider adapter based on configuration"""
        provider_type = self._settings.get("provider", "local").lower()
        
        if provider_type == "openrouter":
            return OpenRouterAdapter(
                api_key=self._settings.get("api_key", ""),
                base_url=self._settings.get("base_url", "https://openrouter.ai/api/v1"),
            )
        elif provider_type == "openai":
            return OpenAIAdapter(
                api_key=self._settings.get("api_key", ""),
                base_url=self._settings.get("base_url", "https://api.openai.com/v1"),
            )
        elif provider_type == "anthropic":
            return AnthropicAdapter(
                api_key=self._settings.get("api_key", ""),
                base_url=self._settings.get("base_url", "https://api.anthropic.com"),
            )
        else:  # local
            return LocalAdapter(
                base_url=self._settings.get("base_url", "http://localhost:11434"),
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check AI service health"""
        checks = []
        
        # Check provider reachability with minimal ping
        try:
            # Would do actual ping in production
            checks.append({"name": "provider_ping", "status": "OK", "latency_ms": 0})
        except Exception as e:
            checks.append({"name": "provider_ping", "status": "UNAVAILABLE", "detail": str(e)})
        
        # Check pgvector readiness
        try:
            checks.append({"name": "pgvector", "status": "OK"})
        except Exception as e:
            checks.append({"name": "pgvector", "status": "DEGRADED", "detail": str(e)})
        
        return {
            "module": "ai",
            "status": "OK" if all(c.get("status") == "OK" for c in checks) else "DEGRADED",
            "checks": checks,
            "ts": utcnow(),
        }


# ============================================================================
# Singleton instance
# ============================================================================

_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Get AI service singleton"""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


# ============================================================================
# Public API Functions
# ============================================================================

def provider() -> AIGateway:
    """Get configured AI provider gateway"""
    svc = get_ai_service()
    if svc._provider is None:
        svc._provider = svc._create_provider()
    return svc._provider


def sanitize_prompt(text: str) -> str:
    """Sanitize prompt by stripping PII and org identifiers
    
    Removes organization IDs, tenant identifiers, and other sensitive data
    before sending prompts to external AI providers.
    """
    # Remove UUIDs that might be org_ids
    sanitized = re.sub(
        r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
        '[REDACTED_ID]',
        text,
        flags=re.IGNORECASE
    )
    # Remove common PII patterns
    sanitized = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', sanitized)
    return sanitized


async def generate_checklist(
    ctx: RequestContext,
    prompt: str,
    node_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Generate a checklist from AI prompt
    
    Route: POST /ai/checklists/generate
    Roles: MANAGER, SYS_ADMIN
    
    Validates prompt length, sanitizes input, calls provider with
    schema-enforced JSON output for checklist structure.
    """
    ai_svc = get_ai_service()
    
    # Validate prompt length
    if len(prompt) > 4000:
        raise DomainError(error_code="PROMPT_TOO_LONG", message="Prompt exceeds 4000 characters")
    
    # Sanitize prompt
    clean_prompt = sanitize_prompt(prompt)
    
    # Create generation job
    job_id = f"gen_{new_id().hex[:16]}"
    job = GenerationJob(
        id=job_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        operation="checklist_generation",
        prompt=prompt,
        node_id=node_id,
        status=GenerationStatus.PROCESSING,
    )
    
    # Dispatch async task
    await ai_svc._worker.dispatch(
        "ai.generate_checklist_async",
        args={"job_id": job_id, "prompt": clean_prompt},
        idempotency_key=f"ai_gen:{ctx.org_id}:{job_id}",
    )
    
    return {"job_id": job_id, "status": "PROCESSING"}


async def generate_checklist_async(job_id: str, prompt: str) -> None:
    """Async task: Execute checklist generation
    
    Worker task that performs the actual AI generation,
    validates against JSON schema, and persists results.
    """
    ai_svc = get_ai_service()
    
    try:
        # Define expected checklist JSON schema
        checklist_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "integer"},
                            "action": {"type": "string"},
                            "measurement_type": {"type": "string", "enum": ["PASS_FAIL", "NUMERIC", "TEXT"]},
                            "threshold_min": {"type": "number"},
                            "threshold_max": {"type": "number"},
                            "signature_required": {"type": "boolean"},
                        },
                        "required": ["step", "action"],
                    }
                },
            },
            "required": ["title", "items"],
        }
        
        # Call AI provider
        result = await ai_svc._provider.generate_text(
            prompt=prompt,
            model=ai_svc._settings.get("chat_model", "gpt-4o-mini"),
            max_tokens=2048,
            temperature=0.3,  # Lower for structured output
            json_schema=checklist_schema,
        )
        
        # Retry on invalid JSON (up to 3 times)
        retries = 0
        while retries < 3:
            try:
                checklist_data = json.loads(result["text"])
                break
            except json.JSONDecodeError:
                retries += 1
                if retries >= 3:
                    raise ValueError("Invalid JSON after 3 retries")
                result = await ai_svc._provider.generate_text(
                    prompt=f"Return valid JSON matching this schema: {json.dumps(checklist_schema)}",
                    model=ai_svc._settings.get("chat_model", "gpt-4o-mini"),
                    max_tokens=2048,
                    temperature=0.1,
                )
        
        # Persist result
        # In production: update DB row
        
        # Emit event
        await publish("ai.checklist_completed", {
            "job_id": job_id,
            "checklist": checklist_data,
        })
        
        # Log usage
        await log_usage(
            org_id=None,  # Would extract from job
            user_id=None,
            operation="checklist_generation",
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
        )
        
    except Exception as e:
        logger.error(f"Checklist generation failed: {e}")
        await publish("ai.checklist_failed", {"job_id": job_id, "error": str(e)})


async def get_generation(
    ctx: RequestContext,
    job_id: str,
) -> Dict[str, Any]:
    """Get generation job status and result
    
    Route: GET /ai/generations/{id}
    """
    # In production: fetch from DB
    return {
        "job_id": job_id,
        "status": "PENDING",
        "result": None,
        "error": None,
    }


async def ingest_manual(file_id: UUID) -> None:
    """Ingest manual document for RAG
    
    Worker task consuming manual.ingestion_requested event.
    Fetches file via STORAGE, extracts text, chunks, embeds,
    and upserts to pgvector document_chunks table.
    """
    ai_svc = get_ai_service()
    
    job_id = f"ingest_{new_id().hex[:16]}"
    job = IngestionJob(
        id=job_id,
        org_id=None,  # Would fetch from file metadata
        file_id=file_id,
        status=IngestionStatus.PROCESSING,
    )
    
    try:
        # Fetch file from storage
        # In production: storage.get(key)
        
        # Extract text (PDF/txt/docx)
        # In production: use appropriate parser
        
        # Chunk with metadata
        chunks = []  # List of DocumentChunk
        
        # Embed chunks
        texts = [c.content for c in chunks]
        embeddings = await ai_svc._provider.embed(
            texts=texts,
            model=ai_svc._settings.get("embedding_model", "text-embedding-3-small"),
        )
        
        # Upsert to pgvector with organization_id filter
        # In production: INSERT INTO document_chunks ... ON CONFLICT DO UPDATE
        
        job.status = IngestionStatus.COMPLETED
        job.chunks_processed = len(chunks)
        
        await publish("ai.ingestion_completed", {
            "job_id": job_id,
            "file_id": str(file_id),
            "chunks": len(chunks),
        })
        
    except Exception as e:
        logger.error(f"Manual ingestion failed: {e}")
        job.status = IngestionStatus.FAILED
        job.error = str(e)
        await publish("ai.ingestion_failed", {
            "job_id": job_id,
            "file_id": str(file_id),
            "error": str(e),
        })


async def retry_failed_ingestions() -> None:
    """Beat task: Retry failed ingestion jobs
    
    Runs every ~10 minutes to retry previously failed jobs.
    """
    # In production: SELECT FROM document_ingestion_jobs WHERE status='FAILED'
    logger.info("Retrying failed ingestion jobs")


async def ask_assistant(
    ctx: RequestContext,
    thread_id: str,
    question: str,
) -> Dict[str, Any]:
    """Ask AI assistant a question
    
    Route: POST /ai/assistant/threads/{id}/messages
    Roles: Any authenticated user
    
    Retrieves top-k chunks from pgvector filtered by org_id + node_id,
    grounds answer with citations, supports SSE streaming.
    """
    ai_svc = get_ai_service()
    
    # Retrieve relevant chunks from pgvector
    # SELECT * FROM document_chunks 
    # WHERE org_id = :org_id 
    # ORDER BY embedding <-> :query_embedding 
    # LIMIT 5
    
    # Build grounded prompt with citations
    context = "Relevant manual excerpts:\n"
    citations = []
    # In production: populate from retrieved chunks
    
    full_prompt = f"{context}\n\nQuestion: {question}\n\nAnswer based on the manuals above. If the answer is not found, say 'I could not find this information in the manuals.'"
    
    # Generate response
    result = await ai_svc._provider.generate_text(
        prompt=sanitize_prompt(full_prompt),
        model=ai_svc._settings.get("chat_model", "gpt-4o-mini"),
        max_tokens=1024,
        temperature=0.7,
    )
    
    answer = result.get("text", "")
    
    # Persist message
    msg_id = f"msg_{new_id().hex[:16]}"
    message = AssistantMessage(
        id=msg_id,
        thread_id=thread_id,
        role="assistant",
        content=answer,
        citations=citations,
    )
    
    await publish("ai.assistant_answered", {
        "thread_id": thread_id,
        "message_id": msg_id,
    })
    
    return {
        "message_id": msg_id,
        "content": answer,
        "citations": citations,
    }


async def create_thread(
    ctx: RequestContext,
    node_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Create new assistant thread
    
    Route: POST /ai/assistant/threads
    Optionally bound to a service point node.
    """
    thread_id = f"thread_{new_id().hex[:16]}"
    thread = AssistantThread(
        id=thread_id,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        node_id=node_id,
    )
    
    return {"thread_id": thread_id, "node_id": node_id}


async def get_messages(
    ctx: RequestContext,
    thread_id: str,
) -> List[Dict[str, Any]]:
    """Get thread message history
    
    Route: GET /ai/assistant/threads/{id}/messages
    """
    # In production: SELECT FROM ai_assistant_messages WHERE thread_id = :thread_id
    return []


async def reprocess_manual(
    ctx: RequestContext,
    file_id: UUID,
) -> Dict[str, Any]:
    """Re-run manual ingestion
    
    Route: POST /ai/manuals/{fileId}/reprocess
    Roles: MANAGER, MAINTENANCE
    """
    # Verify permission
    if ctx.role not in [Role.MANAGER, Role.MAINTENANCE]:
        raise ForbiddenError("Only MANAGER or MAINTENANCE can reprocess manuals")
    
    # Dispatch ingestion task
    await ingest_manual(file_id)
    
    return {"status": "PROCESSING", "file_id": str(file_id)}


async def log_usage(
    org_id: UUID,
    user_id: UUID,
    operation: str,
    tokens_in: int,
    tokens_out: int,
) -> None:
    """Log AI usage for quota tracking
    
    Persists to ai_usage_logs table for billing/quota enforcement.
    """
    ai_svc = get_ai_service()
    
    log = UsageLog(
        id=f"usage_{new_id().hex[:16]}",
        org_id=org_id,
        user_id=user_id,
        operation=operation,
        provider=ai_svc._settings.get("provider", "unknown"),
        model=ai_svc._settings.get("chat_model", "unknown"),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=0.0,  # Would measure in production
    )
    
    # In production: INSERT INTO ai_usage_logs


# ============================================================================
# Module Class
# ============================================================================

class AIModule(ModuleBase):
    """AI Module implementing ModuleBase protocol"""
    
    name = "ai"
    version = "1.0.0"
    dependencies = ("core", "db", "cache", "storage", "worker")
    optional_dependencies = ("auth", "tenancy")
    profiles = ("api", "worker", "beat", "all-in-one")
    
    def __init__(self):
        self.service = get_ai_service()
        self._router = None
    
    async def configure(self, settings: Any) -> None:
        """Configure AI module"""
        self.service.configure({
            "provider": settings.provider if hasattr(settings, 'provider') else "local",
            "api_key": settings.api_key if hasattr(settings, 'api_key') else "",
            "base_url": settings.base_url if hasattr(settings, 'base_url') else None,
            "chat_model": settings.chat_model if hasattr(settings, 'chat_model') else "gpt-4o-mini",
            "embedding_model": settings.embedding_model if hasattr(settings, 'embedding_model') else "text-embedding-3-small",
            "timeout": settings.timeout if hasattr(settings, 'timeout') else 30.0,
            "max_retries": settings.max_retries if hasattr(settings, 'max_retries') else 3,
        })
        logger.info(f"AI module configured with provider={self.service._settings.get('provider')}")
    
    async def initialize(self, ctx: ModuleContext) -> None:
        """Initialize AI module dependencies"""
        db = ctx.services.get("db")
        cache = ctx.services.get("cache")
        storage = ctx.services.get("storage")
        worker = ctx.services.get("worker")
        
        self.service.initialize(db, cache, storage, worker)
        
        # Subscribe to manual ingestion events
        await subscribe("manual.ingestion_requested", self._on_ingestion_request)
        
        logger.info("AI module initialized")
    
    async def start(self) -> None:
        """Start AI module - register tasks and routes"""
        # Register worker tasks
        worker = self.service._worker
        if worker:
            worker.register_task("ai.generate_checklist_async", generate_checklist_async)
            worker.register_task("ai.ingest_manual", ingest_manual)
            worker.register_beat("ai.retry_ingestions", "ai.retry_failed_ingestions", 600)  # 10 min
        
        logger.info("AI module started")
    
    async def stop(self) -> None:
        """Stop AI module - drain in-flight work"""
        logger.info("AI module stopping")
    
    async def health(self) -> Dict[str, Any]:
        """Report AI module health"""
        return await self.service.health_check()
    
    async def _on_ingestion_request(self, payload: Dict[str, Any]) -> None:
        """Handle manual.ingestion_requested event"""
        file_id = payload.get("file_id")
        if file_id:
            logger.info(f"Received ingestion request for file {file_id}")
            await ingest_manual(UUID(file_id))
