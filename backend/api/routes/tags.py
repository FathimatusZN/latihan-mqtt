"""
============================================================
 FILE    : backend/api/routes/tags.py
 FUNGSI  : REST endpoints untuk manajemen tags per device
============================================================
"""

import logging
import psycopg2

from fastapi import APIRouter, HTTPException
from models.schemas import TagCreate, TagUpdate
from repositories import tag_repo
from services import subscription_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tags"])


@router.get("/tags", summary="Daftar semua tag (opsional filter device)")
def list_all_tags(device_id: str | None = None):
    data = tag_repo.list_tags(device_id=device_id)
    return {"total": len(data), "data": data}


@router.get("/devices/{device_id}/tags", summary="Daftar tag milik satu device")
def list_device_tags(device_id: str):
    data = tag_repo.list_tags(device_id=device_id)
    return {"device_id": device_id, "total": len(data), "data": data}


@router.post(
    "/devices/{device_id}/tags",
    summary="Tambah tag ke device",
    status_code=201,
)
def create_tag(device_id: str, body: TagCreate):
    try:
        new_id = tag_repo.create_tag(device_id, body.model_dump())
        # mqtt_topic di-generate oleh repository
        tags   = tag_repo.list_tags(device_id=device_id)
        tag    = next((t for t in tags if t["id"] == new_id), None)
        subscription_manager.sync()
        return {
            "success":   True,
            "id":        new_id,
            "mqtt_topic": tag["mqtt_topic"] if tag else None,
        }
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            409,
            detail=f"Tag '{body.tag_name}' sudah ada di device '{device_id}'",
        )
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(404, detail=f"Device '{device_id}' tidak ditemukan")
    except Exception as e:
        logger.error(f"❌ create_tag error: {e}")
        raise HTTPException(500, detail="Database error")


@router.put(
    "/devices/{device_id}/tags/{tag_name}",
    summary="Update konfigurasi tag",
)
def update_tag(device_id: str, tag_name: str, body: TagUpdate):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, detail="Tidak ada field yang diupdate")
    ok = tag_repo.update_tag(device_id, tag_name, data)
    if not ok:
        raise HTTPException(
            404,
            detail=f"Tag '{tag_name}' pada device '{device_id}' tidak ditemukan",
        )
    subscription_manager.sync()
    return {"success": True, "device_id": device_id, "tag_name": tag_name}


@router.delete(
    "/devices/{device_id}/tags/{tag_name}",
    summary="Hapus tag dari device",
)
def delete_tag(device_id: str, tag_name: str):
    ok = tag_repo.delete_tag(device_id, tag_name)
    if not ok:
        raise HTTPException(
            404,
            detail=f"Tag '{tag_name}' pada device '{device_id}' tidak ditemukan",
        )
    subscription_manager.sync()
    return {"success": True, "deleted": f"{device_id}/{tag_name}"}