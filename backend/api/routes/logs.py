"""
============================================================
 FILE    : backend/api/routes/logs.py
 FUNGSI  : REST endpoints untuk query log data & dashboard
============================================================
"""

from fastapi import APIRouter, Query
from typing import Optional
from repositories import log_repo

router = APIRouter(tags=["logs"])


@router.get("/logs", summary="Query log readings")
def get_logs(
    device_id: Optional[str] = Query(default=None),
    tag_name:  Optional[str] = Query(default=None),
    status:    Optional[str] = Query(default=None),
    limit:     int           = Query(default=100, ge=1, le=1000),
):
    data = log_repo.query_logs(
        device_id=device_id,
        tag_name=tag_name,
        status=status,
        limit=limit,
    )
    return {"total": len(data), "data": data}


@router.get("/statistik", summary="Statistik 24 jam per device+tag")
def get_statistik():
    data = log_repo.get_statistik_24h()
    return {"periode": "24 jam terakhir", "data": data}


@router.get("/unknown-messages", summary="Log pesan topic tidak dikenal")
def get_unknown_messages(limit: int = Query(default=50, ge=1, le=200)):
    data = log_repo.query_unknown_messages(limit=limit)
    return {"total": len(data), "data": data}