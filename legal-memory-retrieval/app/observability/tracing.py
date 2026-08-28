from __future__ import annotations

from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_provider: TracerProvider | None = None


def setup_tracing(service_name: str = "legal-memory-retrieval") -> None:
    global _provider
    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)
    # Console exporter so traces are visible in logs without an external collector
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("legal-memory-retrieval")


@contextmanager
def span(name: str, attributes: dict | None = None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as s:
        if attributes:
            for k, v in attributes.items():
                s.set_attribute(k, str(v))
        yield s
