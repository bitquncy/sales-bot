"""Легковесная система сбора метрик (MONITORING-1).

Собирает метрики производительности и использования без внешних зависимостей.
Для production рекомендуется интеграция с Prometheus/Grafana.
"""

import time
from dataclasses import dataclass, field
from typing import Literal

MetricType = Literal["counter", "gauge", "histogram"]


@dataclass
class Metric:
    """Одна метрика с временными метками."""
    name: str
    type: MetricType
    value: float = 0.0
    count: int = 0
    min_value: float = float('inf')
    max_value: float = float('-inf')
    sum_value: float = 0.0
    last_updated: float = field(default_factory=time.time)


class MetricsCollector:
    """Простой in-memory сборщик метрик.
    
    Для production используйте Prometheus client library.
    """
    
    def __init__(self):
        self._metrics: dict[str, Metric] = {}
        self._start_time = time.time()
    
    def increment(self, name: str, value: float = 1.0) -> None:
        """Увеличивает счетчик."""
        if name not in self._metrics:
            self._metrics[name] = Metric(name=name, type="counter")
        
        metric = self._metrics[name]
        metric.value += value
        metric.count += 1
        metric.last_updated = time.time()
    
    def set_gauge(self, name: str, value: float) -> None:
        """Устанавливает значение gauge (текущее состояние)."""
        if name not in self._metrics:
            self._metrics[name] = Metric(name=name, type="gauge")
        
        metric = self._metrics[name]
        metric.value = value
        metric.last_updated = time.time()
    
    def observe(self, name: str, value: float) -> None:
        """Добавляет наблюдение в histogram (для измерения времени, размеров и т.д.)."""
        if name not in self._metrics:
            self._metrics[name] = Metric(name=name, type="histogram")
        
        metric = self._metrics[name]
        metric.count += 1
        metric.sum_value += value
        metric.min_value = min(metric.min_value, value)
        metric.max_value = max(metric.max_value, value)
        metric.last_updated = time.time()
    
    def get_metrics(self) -> dict[str, dict]:
        """Возвращает все метрики в структурированном виде."""
        result = {}
        
        for name, metric in self._metrics.items():
            data = {
                "type": metric.type,
                "last_updated": metric.last_updated,
            }
            
            if metric.type == "counter":
                data["value"] = metric.value
                data["count"] = metric.count
            elif metric.type == "gauge":
                data["value"] = metric.value
            elif metric.type == "histogram":
                data["count"] = metric.count
                data["sum"] = metric.sum_value
                data["min"] = metric.min_value if metric.count > 0 else None
                data["max"] = metric.max_value if metric.count > 0 else None
                data["avg"] = metric.sum_value / metric.count if metric.count > 0 else None
            
            result[name] = data
        
        # Добавляем uptime
        result["uptime_seconds"] = {
            "type": "gauge",
            "value": time.time() - self._start_time,
        }
        
        return result
    
    def reset(self) -> None:
        """Сбрасывает все метрики (для тестов)."""
        self._metrics.clear()
        self._start_time = time.time()


# Глобальный экземпляр
_collector = MetricsCollector()


def increment(name: str, value: float = 1.0) -> None:
    """Увеличивает счетчик."""
    _collector.increment(name, value)


def set_gauge(name: str, value: float) -> None:
    """Устанавливает gauge."""
    _collector.set_gauge(name, value)


def observe(name: str, value: float) -> None:
    """Добавляет наблюдение в histogram."""
    _collector.observe(name, value)


def get_metrics() -> dict[str, dict]:
    """Возвращает все метрики."""
    return _collector.get_metrics()


def reset() -> None:
    """Сбрасывает метрики (для тестов)."""
    _collector.reset()


class timer:
    """Context manager для измерения времени выполнения.
    
    Usage:
        with timer("operation_name"):
            # код операции
    """
    
    def __init__(self, name: str):
        self.name = name
        self.start_time = 0.0
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        observe(f"{self.name}_duration_seconds", duration)
        return False


# Примеры использования метрик:
# 
# # Счетчики (монотонно растут)
# increment("bot.messages_received")
# increment("bot.callbacks_received")
# increment("ai.analyze_company_calls")
# increment("ai.rate_limit_errors")
# 
# # Gauges (текущее значение)
# set_gauge("bot.active_users", 42)
# set_gauge("db.leads_total", 156)
# 
# # Histogram (распределение значений)
# observe("ai.analyze_duration_seconds", 2.5)
# observe("db.query_duration_seconds", 0.012)
# 
# # Таймер
# with timer("expensive_operation"):
#     await expensive_operation()
