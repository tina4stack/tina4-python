# Tina4 Queue - AMQP URL parsing. Zero dependencies.
"""
Parse an AMQP URL into connection config, per the RabbitMQ URI spec.

THE VHOST IS THE PATH SEGMENT, URL-DECODED, WITH NO LEADING SLASH.
That single rule is the whole reason this module exists as its own file: all
four Tina4 frameworks used to prepend a "/" to whatever followed the host, so

    amqp://guest:guest@rabbit:5672/orders

asked the broker for a virtual host literally named "/orders". No broker has
that - the vhost is named "orders" - so every publish failed against a named
vhost, which is the ordinary multi-tenant RabbitMQ setup and the exact form
every RabbitMQ tutorial shows. MEASURED against a real broker: 4 of 5 URL
shapes resolved to the wrong name, and the only one that worked was the one
carrying no vhost at all. That is why four green suites never noticed - every
test and every dev box used the default vhost.

Percent-decoding matters for the same reason: the DEFAULT vhost is named "/",
which cannot be written literally in a path, so the spec spells it "%2f".
Without decoding, "amqp://host/%2f" asks for a vhost named "%2f".

  amqp://host              -> vhost unset, caller's default ("/")
  amqp://host/             -> vhost unset, caller's default ("/")   [see below]
  amqp://host/orders       -> "orders"
  amqp://host/%2f          -> "/"
  amqp://host/a%2Fb        -> "a/b"

DELIBERATE DEVIATION, one shape: the spec's own table reads a bare trailing
slash as the EMPTY vhost name "". Tina4 treats it as "no vhost given" and
leaves the caller's default in place. Nobody writes a trailing slash intending
a vhost whose name is the empty string, no broker ships one, and reading it
literally would turn a working "amqp://host:5672/" into a connection failure
for no benefit. Every other shape follows the spec exactly.
"""
from urllib.parse import unquote


def parse_amqp_url(url: str) -> dict:
    """Parse amqp://user:pass@host:port/vhost into a config dict.

    Only keys actually present in the URL are set, so a caller's own defaults
    survive for everything the URL does not mention.
    """
    config = {}
    rest = url
    for scheme in ("amqp://", "amqps://"):
        if rest.startswith(scheme):
            rest = rest[len(scheme):]
            break

    if "@" in rest:
        creds, rest = rest.split("@", 1)
        if ":" in creds:
            config["username"], config["password"] = creds.split(":", 1)
        else:
            config["username"] = creds

    if "/" in rest:
        hostport, vhost = rest.split("/", 1)
        # An empty segment means "not specified" - see the deviation note above.
        if vhost:
            config["vhost"] = unquote(vhost)
    else:
        hostport = rest

    if ":" in hostport:
        host, port = hostport.split(":", 1)
        config["host"] = host
        config["port"] = int(port)
    elif hostport:
        config["host"] = hostport
    return config
