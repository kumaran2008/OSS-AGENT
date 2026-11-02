import re
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple


@dataclass(frozen=True, slots=True)
class RouteDecision:
    tier: int                     # 0, 1, 2, 3, 4
    engine_name: str              # "micro_reflex", "edge_slm", "deepseek_flash", "desktop_cdp", "google_live"
    confidence: float             # 0.0 to 1.0
    complexity_score: float       # 0.0 to 1.0
    action_tag: Optional[str] = None


class RadixTrieNode:
    __slots__ = ("children", "action_tag")

    def __init__(self):
        self.children: Dict[str, RadixTrieNode] = {}
        self.action_tag: Optional[str] = None


class LatentComplexityGate:
    """
    Sub-15ms Radix-Tree and Token-Complexity Gate.
    Determines minimal compute tier and cost profile for any incoming query.
    """

    CODE_TOKENS = re.compile(
        r"\b(def|class|async|await|refactor|optimize|test|git|patch|merge|docker|pipeline|indexerror|traceback|syntaxerror|sql|schema|api|bug|fix|function)\b",
        re.IGNORECASE
    )

    MULTIHOP_TOKENS = re.compile(
        r"\b(why|compare|contrast|difference|architect|analyze|evaluate|explain\s+how)\b",
        re.IGNORECASE
    )

    def __init__(self):
        self.root = RadixTrieNode()
        self._populate_tier0_trie()

    def _populate_tier0_trie(self):
        tier0_commands = {
            "stop": "ABORT",
            "cancel": "ABORT",
            "halt": "ABORT",
            "shut up": "AUDIO_MUTE",
            "mute": "AUDIO_MUTE",
            "clear screen": "TERM_CLEAR",
            "clear": "TERM_CLEAR",
            "status": "SYS_STATUS",
            "who are you": "IDENTITY",
            "ping": "PONG"
        }
        for phrase, tag in tier0_commands.items():
            self._insert_phrase(phrase, tag)

    def _insert_phrase(self, phrase: str, tag: str):
        node = self.root
        tokens = phrase.lower().strip().split()
        for tok in tokens:
            if tok not in node.children:
                node.children[tok] = RadixTrieNode()
            node = node.children[tok]
        node.action_tag = tag

    def _match_tier0(self, text: str) -> Optional[str]:
        tokens = text.lower().strip().split()
        if not tokens:
            return None
        node = self.root
        for tok in tokens:
            if tok in node.children:
                node = node.children[tok]
            else:
                return None
        return node.action_tag

    def route(
        self,
        prompt: str,
        budget_available: bool = True,
        preferred_backend: Optional[str] = None
    ) -> RouteDecision:
        """
        Calculates execution tier in <15ms.
        """
        clean_text = prompt.strip().lower()

        # 1. Micro-Reflex Path (Tier 0)
        action_tag = self._match_tier0(clean_text)
        if action_tag:
            return RouteDecision(
                tier=0,
                engine_name="micro_reflex",
                confidence=1.0,
                complexity_score=0.0,
                action_tag=action_tag
            )

        # 2. Syntax & Structural Token Density
        words = clean_text.split()
        word_count = len(words)
        code_matches = len(self.CODE_TOKENS.findall(clean_text))
        multihop_matches = len(self.MULTIHOP_TOKENS.findall(clean_text))

        # Dynamic Complexity Score Calculation
        complexity = min(
            1.0,
            (code_matches * 0.35) + (multihop_matches * 0.25) + (min(word_count, 60) / 100.0)
        )

        # 3. Honor Sticky User Preferences if Explicitly Defined
        if preferred_backend == "google_live":
            return RouteDecision(tier=4, engine_name="google_live", confidence=0.95, complexity_score=complexity)
        if preferred_backend == "desktop_cdp":
            return RouteDecision(tier=3, engine_name="desktop_cdp", confidence=0.90, complexity_score=complexity)
        if preferred_backend == "slm_local":
            return RouteDecision(tier=1, engine_name="edge_slm", confidence=0.88, complexity_score=complexity)

        # 4. Tier 1: Local Edge SLM (Low Complexity Banter / Greetings / Simple Queries)
        if complexity <= 0.30 and code_matches == 0:
            return RouteDecision(
                tier=1,
                engine_name="edge_slm",
                confidence=0.92,
                complexity_score=complexity
            )

        # 5. Tier 2 vs Tier 3: Complex Code & Reasoning Tasks
        if budget_available:
            return RouteDecision(
                tier=2,
                engine_name="deepseek_flash",
                confidence=0.96,
                complexity_score=complexity
            )
        else:
            return RouteDecision(
                tier=3,
                engine_name="desktop_cdp",
                confidence=0.85,
                complexity_score=complexity
            )
