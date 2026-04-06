"""
============================================================
 FILE    : backend/api/routes/mqtt.py
 FUNGSI  : REST endpoints untuk info & kontrol MQTT
============================================================
"""

from fastapi import APIRouter
from services import subscription_manager

router = APIRouter(prefix="/mqtt", tags=["mqtt"])


@router.get("/info", summary="Info broker dan subscriptions aktif")
def mqtt_info():
    return {
        "subscribed_topics": sorted(subscription_manager.get_subscribed()),
        "total_topics":      len(subscription_manager.get_subscribed()),
    }


@router.post("/sync", summary="Paksa sinkronisasi ulang subscriptions dari DB")
def force_sync():
    before = sorted(subscription_manager.get_subscribed())
    result = subscription_manager.sync()
    after  = sorted(subscription_manager.get_subscribed())
    return {
        "success": True,
        "before":  before,
        "after":   after,
        "added":   result["added"],
        "removed": result["removed"],
    }