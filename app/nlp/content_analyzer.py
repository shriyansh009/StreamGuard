"""StreamGuard NLP Content Analysis Engine.

Performs rule-based pattern matching and heuristic toxicity analysis on streaming
chat messages, slurs, threats, harassment, profanity, and spam detection.
"""

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Pattern, Tuple

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """Configurable NLP content analysis engine for stream moderation.

    Analyzes text streams for hate speech, profanity, physical threats,
    harassment, and repetitive spam patterns using pre-compiled regular
    expressions with severity weights.
    """

    # Category severity weights as specified
    WEIGHT_THREAT: float = 0.95
    WEIGHT_HATE_SPEECH: float = 0.90
    WEIGHT_PROFANITY: float = 0.70
    WEIGHT_HARASSMENT: float = 0.60
    WEIGHT_SPAM: float = 0.40

    # List of (regex_pattern, severity_weight) tuples covering key moderation categories
    TOXIC_PATTERNS: List[Tuple[str, float]] = [
        # Threat patterns (weight 0.95)
        (r"\b(?:i\s*(?:will|'ll)?\s*(?:kill|murder|slaughter|shoot|stab|strangle)\s+(?:you|u))\b", 0.95),
        (r"\b(?:kill\s+your\s*self|go\s+die|commit\s+suicide|kys)\b", 0.95),
        (r"\b(?:hope\s+you\s+(?:die|get\s+cancer|burn\s+in\s+hell))\b", 0.95),
        (r"\b(?:bomb|blow\s+up|burn\s+down)\s+(?:your|the)\s+(?:house|school|building|family)\b", 0.95),
        (r"\b(?:put\s+a\s+bullet\s+in\s+(?:you|your\s+head)|slit\s+your\s+throat)\b", 0.95),

        # Hate speech patterns (weight 0.90)
        (r"\b(?:n+[i1!]+g+g+[e3a]+r?s?|n+[i1!]+g+a+s?)\b", 0.90),
        (r"\b(?:f+[a4]+g+g+[o0]+t+s?|f+[a4]+g+s?)\b", 0.90),
        (r"\b(?:k+[i1!]+k+[e3]+s?|ch+[i1!]+n+k+s?|sp+[i1!]+c+s?|w+[e3]+tb+[a4]+ck+s?)\b", 0.90),
        (r"\b(?:tr+[a4]+nn+(?:y|ies)|shemale|he-she)\b", 0.90),
        (r"\b(?:gas\s+the\s+jews|white\s+power|heil\s+hitler|kill\s+all\s+(?:blacks|whites|muslims|jews|gays))\b", 0.90),
        (r"\b(?:subhuman|parasites|vermin)\s+(?:race|ethnicity|people|group)\b", 0.90),

        # Profanity patterns (weight 0.70)
        (r"\b(?:f+u+c+k+(?:e+r+|i+n+g+|e+d+|s+)?|f+u+k+)\b", 0.70),
        (r"\b(?:s+h+i+t+(?:t+y+|t+e+r+|s+)?)\b", 0.70),
        (r"\b(?:b+i+t+c+h+(?:e+s+|y+)?)\b", 0.70),
        (r"\b(?:a+s+s+h+o+l+e+s?|d+i+c+k+h+e+a+d+s?|c+u+n+t+s?)\b", 0.70),
        (r"\b(?:motherfuck(?:er|ing)?|cocksuck(?:er|ing)?)\b", 0.70),
        (r"\b(?:whore|slut|bastard)\b", 0.70),

        # Harassment patterns (weight 0.60)
        (r"\b(?:you(?:'re|\s+are)\s+(?:so\s+)?(?:ugly|fat|pathetic|worthless|disgusting|stupid|an?\s+idiot))\b", 0.60),
        (r"\b(?:nobody\s+(?:likes|loves)\s+you|everyone\s+hates\s+you|waste\s+of\s+(?:breath|space|life))\b", 0.60),
        (r"\b(?:shut\s+(?:the\s+fuck\s+up|up\s+bitch)|stfu|get\s+lost\s+loser)\b", 0.60),
        (r"\b(?:i(?:'ll|\s+will)\s+(?:doxx?|leak|expose)\s+(?:you|your\s+(?:address|ip|location|nudes)))\b", 0.60),

        # Spam patterns (weight 0.40)
        (r"(.)\1{4,}", 0.40),  # 5+ repeated characters (e.g. 'aaaaaa', '!!!!!')
        (r"\b[A-Z]{6,}\b", 0.40),  # ALL CAPS words of 6 or more letters
        (r"(?:https?:\/\/|t\.me\/|discord\.gg\/|whatsapp\s*\+?[0-9]{8,})", 0.40),  # Suspicious links/handles
        (r"\b(?:free\s+crypto|dm\s+for\s+(?:crypto|signals)|click\s+here\s+to\s+(?:claim|win)|guaranteed\s+profit)\b", 0.40),
        (r"\b(\w+)(?:\s+\1){3,}\b", 0.40),  # Repeated identical word 4+ times
    ]

    # Pattern to category name mapping
    DEFAULT_CATEGORY_MAPPINGS: Dict[str, str] = {
        # Threats
        r"\b(?:i\s*(?:will|'ll)?\s*(?:kill|murder|slaughter|shoot|stab|strangle)\s+(?:you|u))\b": "threat",
        r"\b(?:kill\s+your\s*self|go\s+die|commit\s+suicide|kys)\b": "threat",
        r"\b(?:hope\s+you\s+(?:die|get\s+cancer|burn\s+in\s+hell))\b": "threat",
        r"\b(?:bomb|blow\s+up|burn\s+down)\s+(?:your|the)\s+(?:house|school|building|family)\b": "threat",
        r"\b(?:put\s+a\s+bullet\s+in\s+(?:you|your\s+head)|slit\s+your\s+throat)\b": "threat",

        # Hate speech
        r"\b(?:n+[i1!]+g+g+[e3a]+r?s?|n+[i1!]+g+a+s?)\b": "hate_speech",
        r"\b(?:f+[a4]+g+g+[o0]+t+s?|f+[a4]+g+s?)\b": "hate_speech",
        r"\b(?:k+[i1!]+k+[e3]+s?|ch+[i1!]+n+k+s?|sp+[i1!]+c+s?|w+[e3]+tb+[a4]+ck+s?)\b": "hate_speech",
        r"\b(?:tr+[a4]+nn+(?:y|ies)|shemale|he-she)\b": "hate_speech",
        r"\b(?:gas\s+the\s+jews|white\s+power|heil\s+hitler|kill\s+all\s+(?:blacks|whites|muslims|jews|gays))\b": "hate_speech",
        r"\b(?:subhuman|parasites|vermin)\s+(?:race|ethnicity|people|group)\b": "hate_speech",

        # Profanity
        r"\b(?:f+u+c+k+(?:e+r+|i+n+g+|e+d+|s+)?|f+u+k+)\b": "profanity",
        r"\b(?:s+h+i+t+(?:t+y+|t+e+r+|s+)?)\b": "profanity",
        r"\b(?:b+i+t+c+h+(?:e+s+|y+)?)\b": "profanity",
        r"\b(?:a+s+s+h+o+l+e+s?|d+i+c+k+h+e+a+d+s?|c+u+n+t+s?)\b": "profanity",
        r"\b(?:motherfuck(?:er|ing)?|cocksuck(?:er|ing)?)\b": "profanity",
        r"\b(?:whore|slut|bastard)\b": "profanity",

        # Harassment
        r"\b(?:you(?:'re|\s+are)\s+(?:so\s+)?(?:ugly|fat|pathetic|worthless|disgusting|stupid|an?\s+idiot))\b": "harassment",
        r"\b(?:nobody\s+(?:likes|loves)\s+you|everyone\s+hates\s+you|waste\s+of\s+(?:breath|space|life))\b": "harassment",
        r"\b(?:shut\s+(?:the\s+fuck\s+up|up\s+bitch)|stfu|get\s+lost\s+loser)\b": "harassment",
        r"\b(?:i(?:'ll|\s+will)\s+(?:doxx?|leak|expose)\s+(?:you|your\s+(?:address|ip|location|nudes)))\b": "harassment",

        # Spam
        r"(.)\1{4,}": "spam",
        r"\b[A-Z]{6,}\b": "spam",
        r"(?:https?:\/\/|t\.me\/|discord\.gg\/|whatsapp\s*\+?[0-9]{8,})": "spam",
        r"\b(?:free\s+crypto|dm\s+for\s+(?:crypto|signals)|click\s+here\s+to\s+(?:claim|win)|guaranteed\s+profit)\b": "spam",
        r"\b(\w+)(?:\s+\1){3,}\b": "spam",
    }

    def __init__(
        self,
        patterns: Optional[List[Tuple[str, float]]] = None,
        category_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the ContentAnalyzer with pre-compiled patterns.

        Args:
            patterns: Optional custom list of (regex_pattern, severity_weight) tuples.
            category_map: Optional mapping of pattern string to human-readable category name.
        """
        self.raw_patterns = patterns if patterns is not None else self.TOXIC_PATTERNS
        self.category_map = category_map if category_map is not None else self.DEFAULT_CATEGORY_MAPPINGS

        # Pre-compile patterns for maximum runtime throughput.
        # Patterns like ALL CAPS are compiled case-sensitively; others are case-insensitive.
        self._compiled_patterns: List[Tuple[Pattern[str], float, str, bool]] = []
        for pat_str, weight in self.raw_patterns:
            try:
                # Detect case-sensitive patterns (e.g. ALL CAPS)
                is_case_sensitive = "[A-Z]" in pat_str and "[a-z]" not in pat_str
                flags = 0 if is_case_sensitive else re.IGNORECASE
                compiled = re.compile(pat_str, flags)
                category = self.category_map.get(pat_str, self._infer_category(weight))
                self._compiled_patterns.append((compiled, float(weight), category, is_case_sensitive))
            except re.error as e:
                logger.error("Failed to compile moderation pattern '%s': %s", pat_str, e)

        logger.info(
            "ContentAnalyzer initialized with %d active moderation patterns.",
            len(self._compiled_patterns),
        )

    @staticmethod
    def _infer_category(weight: float) -> str:
        """Infer category name from weight when no explicit category is mapped."""
        if weight >= 0.95:
            return "threat"
        if weight >= 0.90:
            return "hate_speech"
        if weight >= 0.70:
            return "profanity"
        if weight >= 0.60:
            return "harassment"
        return "spam"

    def normalize_text(self, text: str) -> str:
        """Lowercase, strip, and normalize unicode text using NFKC.

        Args:
            text: Raw input string to normalize.

        Returns:
            Normalized lowercase string with unicode compatibility characters canonicalized.
        """
        if not text:
            return ""
        try:
            # NFKC decomposes combined characters and replaces compatibility characters with canonical ones
            normalized = unicodedata.normalize("NFKC", text)
            return normalized.strip().lower()
        except Exception as e:
            logger.warning("Error normalizing text: %s. Falling back to basic strip/lower.", e)
            return str(text).strip().lower()

    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze message text for toxicity, threats, profanity, harassment, and spam.

        Args:
            text: Raw input text from the message stream.

        Returns:
            dict containing:
                - toxicity_score: float (0.0 - 1.0, weighted average of matched patterns)
                - flagged: bool (True if score > 0.5)
                - matched_patterns: list[str] (names of matched categories)
                - action_taken: str ('allowed' if score < 0.3, 'flagged' if 0.3 <= score <= 0.7, 'blocked' if score > 0.7)
        """
        if not text or not text.strip():
            return {
                "toxicity_score": 0.0,
                "flagged": False,
                "matched_patterns": [],
                "action_taken": "allowed",
            }

        try:
            # Normalize text for case-insensitive checks
            normalized_lower = self.normalize_text(text)
            # Unicode-normalized original case for case-sensitive checks (e.g. ALL CAPS)
            normalized_cased = unicodedata.normalize("NFKC", text).strip()

            matched_weights: List[float] = []
            matched_categories: List[str] = []

            for compiled, weight, category, is_case_sensitive in self._compiled_patterns:
                target_text = normalized_cased if is_case_sensitive else normalized_lower
                if compiled.search(target_text):
                    matched_weights.append(weight)
                    if category not in matched_categories:
                        matched_categories.append(category)

            if not matched_weights:
                toxicity_score = 0.0
            else:
                # Weighted average of matched patterns as specified
                toxicity_score = round(sum(matched_weights) / len(matched_weights), 4)
                # Ensure bounded between 0.0 and 1.0
                toxicity_score = max(0.0, min(1.0, toxicity_score))

            # Threshold rules
            flagged = toxicity_score > 0.5

            if toxicity_score < 0.3:
                action_taken = "allowed"
            elif toxicity_score <= 0.7:
                action_taken = "flagged"
            else:
                action_taken = "blocked"

            return {
                "toxicity_score": toxicity_score,
                "flagged": flagged,
                "matched_patterns": matched_categories,
                "action_taken": action_taken,
            }

        except Exception as e:
            logger.error("Unexpected error during text analysis: %s", e, exc_info=True)
            # Safe default fallback on error: allow but log
            return {
                "toxicity_score": 0.0,
                "flagged": False,
                "matched_patterns": [],
                "action_taken": "allowed",
            }
