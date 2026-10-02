"""Let chromadb import when Windows Application Control blocks grpcio's DLL.

chromadb imports OpenTelemetry's OTLP gRPC span exporter at startup
(chromadb/telemetry/opentelemetry), which loads grpcio's native `cygrpc` DLL. On
the development machine Smart App Control started blocking that DLL
(2026-09-30). The exporter is only constructed when OpenTelemetry tracing is
enabled (chroma_otel_granularity != "none", default "none"); this project runs a
local PersistentClient with tracing off, so grpc is never actually used.

If the real exporter imports, nothing changes. If it fails, a stand-in module is
registered whose exporter raises a clear error if tracing is ever switched on.
Import this module before `import chromadb`.
"""

from __future__ import annotations

import logging
import sys
import types

logger = logging.getLogger(__name__)

_EXPORTER_MODULE = "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"


class _UnavailableOTLPSpanExporter:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "OpenTelemetry tracing needs grpcio, whose DLL is blocked on this machine "
            "(Windows Application Control). Leave chromadb tracing off."
        )


def install() -> None:
    try:
        __import__(_EXPORTER_MODULE)
        return  # real exporter (and grpcio) loads fine
    except (ImportError, OSError) as exc:
        logger.debug("OTLP gRPC exporter unavailable (%s); using stand-in", exc)
    # Drop any half-imported grpc/exporter modules, then register the stand-in.
    for name in [m for m in sys.modules if m == "grpc" or m.startswith(("grpc.", _EXPORTER_MODULE))]:
        del sys.modules[name]
    stub = types.ModuleType(_EXPORTER_MODULE)
    stub.OTLPSpanExporter = _UnavailableOTLPSpanExporter  # type: ignore[attr-defined]
    sys.modules[_EXPORTER_MODULE] = stub


install()
