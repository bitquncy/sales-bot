"""Простая проверка доступности Redis.

Используется в run.bat для проверки Redis connection без сложного asyncio кода.
"""

import sys


def check_redis(url: str) -> bool:
    """Проверяет доступность Redis по URL.
    
    Returns:
        True если Redis доступен, False иначе
    """
    try:
        # Синхронная проверка через redis-py
        import redis
        client = redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        return True
    except ImportError:
        # redis не установлен
        return False
    except Exception:
        # Redis недоступен или ошибка подключения
        return False


def main():
    """CLI entry point. Exit code 0 = success, 1 = failure."""
    if len(sys.argv) < 2:
        print("Usage: python check_redis.py <redis_url>")
        sys.exit(1)
    
    url = sys.argv[1]
    if check_redis(url):
        print("Redis OK")
        sys.exit(0)
    else:
        print("Redis FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
