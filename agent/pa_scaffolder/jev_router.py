from __future__ import annotations
from typing import Any, Dict, List, Optional
from agent.kernel.jev_ai_system1 import jev_ai_brain, JEVSystemOneDecision
from agent.kernel.model_broker import model_broker

class TypeSafeJEVRouterBridge:
    '''Direct bridge routing GoogleLiveEngine & UnifiedAsyncEngine calls into TypeSafe Jev (jev-1.13.0).'''

    def __init__(self):
        self.harness: Optional[Any] = None

    def bind_harness(self, harness: Any) -> None:
        self.harness = harness

    def classify_and_route(self, transcript: str, context: str = '') -> Dict[str, Any]:
        dec = jev_ai_brain.analyze_situation(transcript=transcript, attached_context=context)
        route = model_broker.route_task_economically(transcript, attached_context=context)
        return {
            'request_id': dec.request_id,
            'model_version': dec.model_version,
            'domain': dec.situational_domain,
            'selected_model': route['selected_model'],
            'provider': route['provider'],
            'target_plugins': dec.target_plugins,
            'recommended_namespaces': dec.recommended_namespaces,
            'emotional_state': dec.emotional_state,
        }

    def route(self, transcript: str, context: str = '', **kwargs: Any) -> Dict[str, Any]:
        return self.classify_and_route(transcript, context=context)

    async def route_live_turn(self, transcript: str, engine: Any = None) -> Dict[str, Any]:
        target_engine = engine or self.harness
        if target_engine is not None and hasattr(target_engine, 'process_voice_turn'):
            return await jev_ai_brain.process_google_live_transcription_through_jev_ai(transcript, target_engine)
        from agent.kernel.universal_orchestrator import universal_orchestrator
        return await universal_orchestrator.execute_google_live_to_jev_pipeline(transcript)

jev_router = TypeSafeJEVRouterBridge()
