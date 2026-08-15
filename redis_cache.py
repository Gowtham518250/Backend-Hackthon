import os

try:
    import redis
except Exception:  # pragma: no cover
    redis = None


def get_redis_client():
    if redis is None:
        return None

    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def cache_answer(key: str, answer: str, ttl: int = 3600):
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl, answer)
        return True
    except Exception:
        return False


def get_cached_answer(key: str):
    client = get_redis_client()
    if client is None:
        return None
    try:
        return client.get(key)
    except Exception:
        return None
