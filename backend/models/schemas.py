"""
============================================================
 FILE    : backend/models/schemas.py
 FUNGSI  : Pydantic schemas untuk validasi request/response API
           dan domain objects internal
============================================================
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ── MQTT PARSED MESSAGE ─────────────────────────────────────
class ParsedMqttMessage:
    """
    Hasil parsing topic MQTT menjadi komponen terstruktur.
    Dibuat di mqtt/consumer.py, diproses di services/ingestion.py
    """
    __slots__ = ("factory_id", "device_id", "tag_name", "raw_topic",
                 "value", "ts_sensor")

    def __init__(
        self,
        factory_id: str,
        device_id: str,
        tag_name: str,
        raw_topic: str,
        value: float,
        ts_sensor: Optional[datetime] = None,
    ):
        self.factory_id = factory_id
        self.device_id  = device_id
        self.tag_name   = tag_name
        self.raw_topic  = raw_topic
        self.value      = value
        self.ts_sensor  = ts_sensor

    def __repr__(self) -> str:
        return (
            f"ParsedMqttMessage(device={self.device_id!r}, "
            f"tag={self.tag_name!r}, value={self.value})"
        )


# ── DEVICE SCHEMAS ──────────────────────────────────────────
class DeviceCreate(BaseModel):
    device_id:    str   = Field(..., min_length=1, max_length=100)
    nama_display: Optional[str] = None
    tipe:         Optional[str] = None
    lokasi:       Optional[str] = None
    factory_id:   str   = "efortech"
    aktif:        bool  = True


class DeviceUpdate(BaseModel):
    nama_display: Optional[str]  = None
    tipe:         Optional[str]  = None
    lokasi:       Optional[str]  = None
    factory_id:   Optional[str]  = None
    aktif:        Optional[bool] = None


class DeviceResponse(BaseModel):
    device_id:    str
    nama_display: Optional[str]
    tipe:         Optional[str]
    lokasi:       Optional[str]
    factory_id:   str
    aktif:        bool
    dibuat_pada:  datetime


# ── TAG SCHEMAS ─────────────────────────────────────────────
class TagCreate(BaseModel):
    tag_name:       str   = Field(..., min_length=1, max_length=100)
    satuan:         Optional[str] = None
    deskripsi:      Optional[str] = None
    batas_warning:  Optional[float] = None
    batas_critical: Optional[float] = None
    aktif:          bool = True


class TagUpdate(BaseModel):
    satuan:         Optional[str]   = None
    deskripsi:      Optional[str]   = None
    batas_warning:  Optional[float] = None
    batas_critical: Optional[float] = None
    aktif:          Optional[bool]  = None


class TagResponse(BaseModel):
    id:             int
    device_id:      str
    tag_name:       str
    satuan:         Optional[str]
    deskripsi:      Optional[str]
    mqtt_topic:     str
    batas_warning:  Optional[float]
    batas_critical: Optional[float]
    aktif:          bool


# ── LOG SCHEMAS ─────────────────────────────────────────────
class LogResponse(BaseModel):
    id:         int
    device_id:  str
    tag_name:   str
    value:      float
    status:     str
    mqtt_topic: Optional[str]
    ts_sensor:  Optional[datetime]
    ts_simpan:  datetime


# ── STATUS / DASHBOARD SCHEMAS ──────────────────────────────
class TagStatusResponse(BaseModel):
    device_id:      str
    nama_display:   Optional[str]
    lokasi:         Optional[str]
    factory_id:     str
    tag_name:       str
    satuan:         Optional[str]
    tag_deskripsi:  Optional[str]
    batas_warning:  Optional[float]
    batas_critical: Optional[float]
    value:          Optional[float]
    status:         Optional[str]
    ts_sensor:      Optional[datetime]
    terakhir_update: Optional[datetime]


class DeviceStatusResponse(BaseModel):
    device_id:    str
    nama_display: Optional[str]
    lokasi:       Optional[str]
    factory_id:   str
    aktif:        bool
    tags:         List[TagStatusResponse]


# ── UNKNOWN MESSAGE LOG ─────────────────────────────────────
class UnknownMessageLog(BaseModel):
    mqtt_topic:  str
    payload_raw: Optional[str]
    alasan:      str