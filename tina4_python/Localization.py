#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
"""Internationalization (i18n) support for Tina4.

Uses Python's built-in ``gettext`` module to provide string
translations. Translation files (``.mo`` / ``.po``) are stored in
``tina4_python/translations/`` and selected via the
``TINA4_LANGUAGE`` environment variable (default: ``en``).

Supported languages are configured in the ``available_languages``
list inside ``localize()``. A command-line argument can also override
the language selection.

Example::

    import os
    os.environ["TINA4_LANGUAGE"] = "fr"
    from tina4_python.Localization import localize
    _ = localize()
    print(_("Hello"))  # → "Bonjour"
"""
import gettext
import os
import sys
from tina4_python.Debug import Debug


AVAILABLE_LANGUAGES = ['en', 'fr', 'af', 'zh', 'ja', 'es']


def localize():
    """Initialize the translation system and return the translation function.

    Returns:
        callable: A function that translates strings based on the active language.
    """
    translation_path = os.path.join(os.path.dirname(__file__), 'translations')

    # get user language from environment variable, default to English
    user_language = os.environ.get('TINA4_LANGUAGE', 'en')

    # check if a CLI argument specifies a language
    for arg in sys.argv[1:]:
        if arg in AVAILABLE_LANGUAGES:
            user_language = arg
            break

    Debug.info("Setting language: " + user_language)

    # Initialize the translation system with fallback to prevent crashes
    translation = gettext.translation(
        'messages',
        translation_path,
        languages=[user_language],
        fallback=True
    )
    translation.install()

    return translation.gettext
