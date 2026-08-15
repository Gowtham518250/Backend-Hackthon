# DeepFind Backend Architecture

This backend supports:
- Owner, Manager, and Employee roles
- customer-based file access
- uploaded document search and Q&A
- Redis cache support
- Gemini-powered answer generation

## Main files
- app.py: main FastAPI app and RAG routes
- customer_api.py: customer, user, file, and role API endpoints
- database.py: SQLite schema and helper functions
- redis_cache.py: Redis helpers
- auth.py: JWT and password helpers
- index.py: document indexing and retrieval logic

## Basics
- Use .env for environment settings.
- Use SQLite for quick local multi-tenant storage.
- Use Redis if available for caching.
- Use Gemini for answer generation.
