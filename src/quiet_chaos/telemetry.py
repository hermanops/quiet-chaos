from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


class NullSpan:
    def set_attribute(self, _key: str, _value: object) -> None:
        return None


class Telemetry:
    def __init__(self, enabled: bool, service_name: str) -> None:
        self.enabled = enabled
        self.service_name = service_name
        self._tracer = None

    def setup(self) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            self.enabled = False
            return

        provider = TracerProvider(resource=Resource.create({"service.name": self.service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer(self.service_name)

    @contextmanager
    def span(self, name: str) -> Iterator[object]:
        if self._tracer is None:
            yield NullSpan()
            return
        with self._tracer.start_as_current_span(name) as span:
            yield span
