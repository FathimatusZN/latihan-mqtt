"""
============================================================
 FILE    : backend/api/routes/devices.py
 FUNGSI  : REST endpoints untuk manajemen devices
============================================================
"""

import logging
import psycopg2

from fastapi import APIRouter, HTTPException
from models.schemas import DeviceCreate, DeviceUpdate
from repositories import device_repo
from services import subscription_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", summary="Daftar semua device")
def list_devices(aktif_only: bool = False):
    data = device_repo.list_devices(aktif_only=aktif_only)
    return {"total": len(data), "data": data}

@router.get("/status", summary="Status terkini semua device aktif")
def get_device_status():
    from repositories import log_repo
    data = log_repo.get_device_status()
    return {"total": len(data), "data": data}


@router.get("/{device_id}", summary="Detail satu device")
def get_device(device_id: str):
    d = device_repo.get_device(device_id)
    if d is None:
        raise HTTPException(404, detail=f"Device '{device_id}' tidak ditemukan")
    return d


@router.post("", summary="Tambah device baru", status_code=201)
def create_device(body: DeviceCreate):
    try:
        new_id = device_repo.create_device(body.model_dump())
        return {"success": True, "device_id": new_id}
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(409, detail=f"Device '{body.device_id}' sudah ada")
    except Exception as e:
        logger.error(f"❌ create_device error: {e}")
        raise HTTPException(500, detail="Database error")


@router.put("/{device_id}", summary="Update konfigurasi device")
def update_device(device_id: str, body: DeviceUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, detail="Tidak ada field yang diupdate")
    ok = device_repo.update_device(device_id, data)
    if not ok:
        raise HTTPException(404, detail=f"Device '{device_id}' tidak ditemukan")
    return {"success": True, "device_id": device_id}


@router.delete("/{device_id}", summary="Hapus device")
def delete_device(device_id: str):
    ok = device_repo.delete_device(device_id)
    if not ok:
        raise HTTPException(404, detail=f"Device '{device_id}' tidak ditemukan")
    subscription_manager.sync()
    return {"success": True, "deleted": device_id}