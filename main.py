#!/usr/bin/python3
#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#

import sys
import jurigged
from tina4_python import webserver
from tina4_python import initialize

jurigged.watch("./src")


def main(in_port=7145):
    print("Starting webserver on", in_port)
    initialize()
    webserver(in_port)


if __name__ == '__main__':
    # Start up a webserver based on params passed on the command line
    port = 7145
    if len(sys.argv) > 1 and sys.argv[1]:
        port = sys.argv[1]
    main(port)
