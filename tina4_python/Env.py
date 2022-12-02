#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os


def load_env(path: str = '.env'):
    env_vars = []
    if not os.path.isfile(path):
        with open(path, 'w') as f:
            f.write("[Project]")
            f.write("\n")

    with open(path, 'r') as f:
        for line in f.readlines():
            if not line.startswith('#') and not line.startswith("["):
                key_value = line.replace('\n', '').split('=')
                env_vars = dict([key_value])
    if len(env_vars) > 0:
        os.environ.update(env_vars)
