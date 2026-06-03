"""Language detection for review text."""

from __future__ import annotations

from appreview.logging import get_logger

logger = get_logger(__name__)

# Default set of languages to detect — covers most mobile app review locales.
# Full language set increases startup time and memory significantly.
DEFAULT_LANGUAGES = [
    "ENGLISH",
    "JAPANESE",
    "CHINESE",
    "KOREAN",
    "GERMAN",
    "FRENCH",
    "SPANISH",
    "ITALIAN",
    "PORTUGUESE",
    "RUSSIAN",
    "ARABIC",
    "HINDI",
]

# ISO 639-1 code mapping from Lingua language names
LANGUAGE_CODE_MAP: dict[str, str] = {
    "ENGLISH": "en",
    "JAPANESE": "ja",
    "CHINESE": "zh",
    "KOREAN": "ko",
    "GERMAN": "de",
    "FRENCH": "fr",
    "SPANISH": "es",
    "ITALIAN": "it",
    "PORTUGUESE": "pt",
    "RUSSIAN": "ru",
    "ARABIC": "ar",
    "HINDI": "hi",
}

# Minimum confidence to accept a detection
MIN_CONFIDENCE = 0.5


class LanguageDetector:
    """Detects the language of review text using lingua-language-detector."""

    def __init__(self, languages: list[str] | None = None) -> None:
        """Initialize the detector with a set of languages.

        Args:
            languages: List of Lingua language names to detect.
                       Defaults to DEFAULT_LANGUAGES.
        """
        self._language_names = languages or DEFAULT_LANGUAGES
        self._detector: object | None = None

    def _get_detector(self) -> object:
        """Lazily initialize the detector (startup cost)."""
        if self._detector is None:
            try:
                from lingua import Language, LanguageDetectorBuilder  # type: ignore[import]

                lingua_langs = []
                for name in self._language_names:
                    try:
                        lingua_langs.append(getattr(Language, name))
                    except AttributeError:
                        logger.warning("Unknown Lingua language name, skipping", name=name)

                if not lingua_langs:
                    msg = "No valid languages configured for detection"
                    raise ValueError(msg)

                self._detector = (
                    LanguageDetectorBuilder.from_languages(*lingua_langs)
                    .with_minimum_relative_distance(MIN_CONFIDENCE)
                    .build()
                )
            except ImportError:
                logger.warning(
                    "lingua-language-detector not available, language detection disabled"
                )
                self._detector = None

        return self._detector  # type: ignore[return-value]

    def detect(self, text: str) -> str | None:
        """Detect the language of a text string.

        Args:
            text: Text to analyze.

        Returns:
            ISO 639-1 language code (e.g., 'ja', 'en'), or None if detection
            fails or confidence is below threshold.
        """
        if not text or not text.strip():
            return None

        detector = self._get_detector()
        if detector is None:
            return None

        try:
            result = detector.detect_language_of(text)  # type: ignore[attr-defined,union-attr]
            if result is None:
                return None
            lang_name = result.name
            return LANGUAGE_CODE_MAP.get(lang_name)
        except Exception as e:
            logger.debug("Language detection failed", error=str(e))
            return None

    def detect_with_confidence(self, text: str) -> tuple[str | None, float]:
        """Detect language with confidence score.

        Args:
            text: Text to analyze.

        Returns:
            Tuple of (ISO 639-1 code or None, confidence 0.0-1.0).
        """
        if not text or not text.strip():
            return None, 0.0

        detector = self._get_detector()
        if detector is None:
            return None, 0.0

        try:
            confidence_values = detector.compute_language_confidence_values(  # type: ignore[attr-defined,union-attr]
                text
            )
            if not confidence_values:
                return None, 0.0

            # Highest confidence language
            best = max(confidence_values, key=lambda x: x.value)  # type: ignore[attr-defined]
            if best.value < MIN_CONFIDENCE:
                return None, float(best.value)

            lang_name = best.language.name  # type: ignore[attr-defined]
            code = LANGUAGE_CODE_MAP.get(lang_name)
            return code, float(best.value)
        except Exception as e:
            logger.debug("Language detection with confidence failed", error=str(e))
            return None, 0.0
