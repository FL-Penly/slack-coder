"""
i18n internationalization module for Slack Coder.

Provides translation support with Chinese (zh) and English (en) languages.
"""

import json
from pathlib import Path
from typing import Optional

_current_language = "zh"  # Default to Chinese
_translations: dict = {}
_fallback_translations: dict = {}  # English as fallback


def _load_translations():
    """Load translation files."""
    global _translations, _fallback_translations
    i18n_dir = Path(__file__).parent

    # Load English as fallback
    en_path = i18n_dir / "en.json"
    if en_path.exists():
        with open(en_path, "r", encoding="utf-8") as f:
            _fallback_translations = json.load(f)

    # Load current language
    lang_path = i18n_dir / f"{_current_language}.json"
    if lang_path.exists():
        with open(lang_path, "r", encoding="utf-8") as f:
            _translations = json.load(f)


def set_language(lang: str):
    """
    Set the current language.

    Args:
        lang: Language code ('en' or 'zh')
    """
    global _current_language
    if lang in ("en", "zh"):
        _current_language = lang
        _load_translations()


def get_language() -> str:
    """
    Get the current language.

    Returns:
        Current language code ('en' or 'zh')
    """
    return _current_language


def t(key: str, **kwargs) -> str:
    """
    Get translated string.

    Args:
        key: Translation key, supports dot notation like "welcome.title"
        **kwargs: Parameters for string formatting

    Returns:
        Translated string, or the key itself if not found

    Example:
        t("welcome.greeting", name="John")  # "Hello, John!"
    """

    def get_nested(d: dict, keys: list) -> Optional[str]:
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return None
        return d if isinstance(d, str) else None

    keys = key.split(".")

    # Try current language first
    value = get_nested(_translations, keys)

    # Fallback to English if not found
    if value is None:
        value = get_nested(_fallback_translations, keys)

    # Return key itself if still not found
    if value is None:
        return key

    # Apply formatting parameters
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value

    return value


# Load translations on import
_load_translations()
