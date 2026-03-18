import os

# Set a 32+ byte SECRET so pyjwt doesn't emit InsecureKeyLengthWarning
os.environ.setdefault("SECRET", "tina4-test-secret-key-32-chars!!")
