"""Shared constants for the One SmartHome integration.

Centralises the handful of values that several modules need: the HA domain,
the protocol vocabulary spoken to a CLU, and the timing of the background
keep-alive / resubscribe work.
"""

from __future__ import annotations

from homeassistant.const import Platform

# Must equal the package folder name; HA keys config entries, the device
# registry and translation files on it.
DOMAIN = "onesmarthome"

# Config-entry keys.
CONF_IP_ADDRESS = "ip_address"
CONF_PORT = "port"
CONF_TOKEN = "token"
CONF_INTERFACE = "interface"

# Object Manager defaults.
DEFAULT_PORT = 9998

# HA platforms this hub fans out to.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.LIGHT,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.COVER,
    Platform.CAMERA,
]

# --- CLU wire protocol vocabulary -------------------------------------------
# A datagram, once decrypted, is UTF-8 text whose fields are colon separated.
WIRE_SEPARATOR = ":"
REQUEST_PREFIX = "req:"
RESPONSE_PREFIX = "resp:"
CLIENT_REPORT_TAG = "clientReport"

# UDP socket / timing tunables (seconds).
RESPONSE_TIMEOUT = 5.0
KEEPALIVE_INTERVAL = 5
RESUBSCRIBE_INTERVAL = 45

# Consecutive failed pings after which a CLU is treated as offline until any
# exchange with it succeeds again.
PING_FAIL_THRESHOLD = 3

# Every CLU registers ALL its keys as one session on its one socket (the only
# shape the main CLU generation here keeps pushing reports for; see
# clu_client). This size only carves the diagnostics view of that list.
REGISTER_CHUNK_SIZE = 1000
