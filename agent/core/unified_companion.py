"""Compatibility Redirect: Pointing to PA Scaffolder Engine Harness"""
from agent.pa_scaffolder.engine_harness import (
    UnifiedAsyncEngine,
    AgentMode,
    PromptDistillationEngine
)
from agent.pa_scaffolder.advanced_companion import (
    AdvancedOBSClient as OBSStudioController,
    AdvancedStreamCompanion as StreamCompanionManager,
    StreamType,
    AudioRoute as AudioChannel
)

__all__ = [
    "UnifiedAsyncEngine",
    "AgentMode",
    "PromptDistillationEngine",
    "OBSStudioController",
    "StreamCompanionManager",
    "StreamType",
    "AudioChannel"
]
