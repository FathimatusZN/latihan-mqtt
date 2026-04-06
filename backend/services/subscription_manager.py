"""
============================================================
 FILE    : backend/services/subscription_manager.py
 FUNGSI  : Kelola set MQTT topics yang disubscribe secara dinamis.
           Sinkronisasi antara state di DB (tabel tags) dan
           state aktual di broker.
============================================================
"""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from repositories import tag_repo

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

_subscribed: set[str] = set()
_client_ref: "mqtt.Client | None" = None


def set_client(client: "mqtt.Client") -> None:
    """Daftarkan referensi ke MQTT client. Dipanggil sekali saat setup."""
    global _client_ref
    _client_ref = client


def sync() -> dict:
    """
    Sinkronkan subscriptions: bandingkan topic di DB dengan
    yang sudah disubscribe, lalu subscribe/unsubscribe seperlunya.

    Return: {"added": [...], "removed": [...]}
    """
    global _subscribed
    if _client_ref is None:
        logger.warning("⚠️  sync() dipanggil sebelum client terdaftar")
        return {"added": [], "removed": []}

    needed   = tag_repo.get_all_active_topics()
    to_add   = needed - _subscribed
    to_remove = _subscribed - needed

    for topic in to_add:
        _client_ref.subscribe(topic, qos=1)
        logger.info(f"📡 Subscribe → {topic}")

    for topic in to_remove:
        _client_ref.unsubscribe(topic)
        logger.info(f"🔕 Unsubscribe → {topic}")

    _subscribed = needed
    return {
        "added":   sorted(to_add),
        "removed": sorted(to_remove),
    }


def get_subscribed() -> set[str]:
    """Return set topics yang sedang aktif disubscribe."""
    return set(_subscribed)