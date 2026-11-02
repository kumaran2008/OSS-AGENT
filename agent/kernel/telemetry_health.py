from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional
import numpy as np


class KernelTelemetryHealthService:
    """OpenTelemetry-Style Hierarchical Span Tracer & Stage Latency Histogram Service."""

    def __init__(self):
        self.stage_samples: Dict[str, List[float]] = {
            "compile_ms": [],
            "policy_ms": [],
            "plugin_exec_ms": [],
            "verify_ms": [],
            "end_to_end_ms": [],
        }
        self._traces: Dict[str, List[Dict[str, Any]]] = {}

    @staticmethod
    def new_trace_id(seed: str = "") -> str:
        return f"trc_{int(time.time() * 1000)}_{hashlib.md5(f'{seed}:{time.time()}'.encode()).hexdigest()[:6]}"

    def record_span(
        self,
        trace_id: str,
        span_name: str,
        duration_ms: float,
        status: str = "OK",
        parent_span: str = "root",
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        span = {
            "trace_id": trace_id,
            "span_id": f"spn_{hashlib.md5(f'{trace_id}:{span_name}:{time.time()}'.encode()).hexdigest()[:8]}",
            "parent_span": parent_span,
            "name": span_name,
            "duration_ms": round(float(duration_ms), 3),
            "status": status,
            "attributes": attributes or {},
            "timestamp": time.time(),
        }
        self._traces.setdefault(trace_id, []).append(span)
        if len(self._traces) > 100:
            oldest = next(iter(self._traces))
            self._traces.pop(oldest, None)
        return span

    def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        return list(self._traces.get(trace_id, []))

    def record_stage_timings(
        self,
        compile_ms: float,
        policy_ms: float,
        plugin_exec_ms: float,
        verify_ms: float,
        end_to_end_ms: float,
    ) -> None:
        for k, v in [
            ("compile_ms", compile_ms),
            ("policy_ms", policy_ms),
            ("plugin_exec_ms", plugin_exec_ms),
            ("verify_ms", verify_ms),
            ("end_to_end_ms", end_to_end_ms),
        ]:
            arr = self.stage_samples[k]
            arr.append(float(v))
            if len(arr) > 300:
                arr.pop(0)

    def get_percentiles(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for stage, vals in self.stage_samples.items():
            if not vals:
                out[stage] = {"p50": 0.0, "p95": 0.0, "p99": 0.0}
            else:
                a = np.array(vals, dtype=np.float32)
                out[stage] = {
                    "p50": round(float(np.percentile(a, 50)), 3),
                    "p95": round(float(np.percentile(a, 95)), 3),
                    "p99": round(float(np.percentile(a, 99)), 3),
                }
        return out


telemetry_health = KernelTelemetryHealthService()
