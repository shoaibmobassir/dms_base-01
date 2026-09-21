from __future__ import annotations

import os
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_provider: TracerProvider | None = None


def setup_tracing(service_name: str = "legal-memory-retrieval") -> None:
    """Console traces always. OTLP only when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    No head sampler that tries to keep slow traces: sampling runs before the
    span finishes, so a latency flag cannot change the decision for that trace.
    """
    global _provider
    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)
    endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if endpoint:
        # Optional extra; imported only when an endpoint is configured.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("legal-memory-retrieval")


@contextmanager
def span(name: str, attributes: dict | None = None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as current:
        if attributes:
            for key, value in attributes.items():
                current.set_attribute(key, str(value))
        yield current
