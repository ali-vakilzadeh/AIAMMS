"""AI Module - Checklist Generation & RAG Assistant

This module implements the AI subsystem for the CMMS server.
It provides:
- Provider abstraction (OpenRouter/OpenAI/Anthropic/local)
- Phase 1: Checklist generation with JSON schema validation
- Phase 2: RAG manual assistant with pgvector embeddings
- Usage tracking, quotas, and rate limits
"""

from .service import (
    AIGateway,
    AIService,
    provider,
    sanitize_prompt,
    generate_checklist,
    generate_checklist_async,
    get_generation,
    ingest_manual,
    retry_failed_ingestions,
    ask_assistant,
    create_thread,
    get_messages,
    reprocess_manual,
    log_usage,
    # Data models
    GenerationJob,
    IngestionJob,
    AssistantThread,
    AssistantMessage,
    DocumentChunk,
    UsageLog,
    # Enums
    ProviderType,
    GenerationStatus,
    IngestionStatus,
)

__all__ = [
    "AIGateway",
    "AIService",
    "provider",
    "sanitize_prompt",
    "generate_checklist",
    "generate_checklist_async",
    "get_generation",
    "ingest_manual",
    "retry_failed_ingestions",
    "ask_assistant",
    "create_thread",
    "get_messages",
    "reprocess_manual",
    "log_usage",
    "GenerationJob",
    "IngestionJob",
    "AssistantThread",
    "AssistantMessage",
    "DocumentChunk",
    "UsageLog",
    "ProviderType",
    "GenerationStatus",
    "IngestionStatus",
]
