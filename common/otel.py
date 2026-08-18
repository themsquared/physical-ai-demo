"""Shared OTel bootstrap for all services.

Spans are the raw material for agentevals (Repeatability pillar): every service
emits them from M1 onward. If no OTLP endpoint is configured we still create
real spans (so tests can assert on them via in-memory processors) but export
nothing.
"""

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def init_tracing(service_name: str) -> trace.Tracer:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
        )

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
