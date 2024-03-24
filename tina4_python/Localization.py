#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import gettext
import os
import sys


# load environment variables from .env file
# check .env for information

def localize():
    translation_path = os.path.join(os.path.dirname(__file__), 'translations')

    available_languages = ['en', 'fr', 'af']

    # get user language from environment variable
    # default to english
    if "TINA4_LANGUAGE" in os.environ:
        user_language = os.environ.get('TINA4_LANGUAGE', 'en')
    else:
        user_language = "en"

    # check if argument is a language
    if len(sys.argv) > 1:
        try:
            int(sys.argv[1])
        except ValueError:
            if sys.argv[1] in available_languages:
                user_language = sys.argv[1]

    if len(sys.argv) > 2 and sys.argv[2] in available_languages:
        user_language = sys.argv[2]
    print("Language: " + user_language)
    # Initialize the translation system
    translation = gettext.translation('messages', translation_path, languages=[user_language])
    translation.install()