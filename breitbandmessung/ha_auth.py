"""Home Assistant ingress user authorization. Fail closed if HA cannot confirm role."""
import json
import logging
import os
import threading
import time
from websocket import create_connection

LOG = logging.getLogger("breitbandmessung.auth")
_CACHE = {}
_CACHE_LOCK = threading.Lock()
ADMIN_GROUP = "system-admin"


def _ha_users():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("SUPERVISOR_TOKEN fehlt")
    ws = create_connection("ws://supervisor/core/websocket", timeout=8)
    try:
        hello = json.loads(ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError("HA WebSocket: Auth-Handshake fehlgeschlagen")
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        authenticated = json.loads(ws.recv())
        if authenticated.get("type") != "auth_ok":
            raise RuntimeError("HA WebSocket: Authentifizierung fehlgeschlagen")
        ws.send(json.dumps({"id": 1, "type": "config/auth/list"}))
        result = json.loads(ws.recv())
        if not result.get("success") or result.get("id") != 1:
            raise RuntimeError("HA Benutzerliste nicht verfügbar")
        return result["result"]
    finally:
        ws.close()


def is_admin(user_id):
    """Admin only if the user is active and HA confirms admin/owner group.

    Cache for at most 45 seconds. When the HA API is unavailable, deny
    privileged operations; never treat all ingress users as administrators.
    """
    if not user_id:
        return False
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(user_id)
        if entry and now - entry[0] < 45:
            return entry[1]
    try:
        users = _ha_users()
        user = next((u for u in users if u.get("id") == user_id), None)
        allowed = bool(user and user.get("is_active", True) and
                       (user.get("is_owner") or ADMIN_GROUP in user.get("group_ids", [])))
        with _CACHE_LOCK:
            _CACHE[user_id] = (now, allowed)
        return allowed
    except Exception as err:
        LOG.warning("HA-Rollenprüfung nicht möglich; Adminrechte verweigert: %s", err)
        return False
