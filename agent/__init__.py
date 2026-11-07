from __future__ import annotations
from agent.kernel.fault_recorder import DiagnosticFaultRecorder

# Automatically initialize global unhandled exception and sys.excepthook tracking
fault_recorder = DiagnosticFaultRecorder()
fault_recorder.install_global_hooks()
