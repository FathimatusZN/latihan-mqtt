"""
============================================================
 FILE    : backend/services/ingestion.py
 FUNGSI  : Business logic untuk memproses pesan MQTT yang
           sudah di-parse oleh consumer.
           Layer ini TIDAK tahu tentang MQTT, psycopg2, dll.
           Input  : ParsedMqttMessage
           Output : simpan ke DB via repository
============================================================
"""

from __future__ import annotations
import logging
from typing import Optional

from models.schemas import ParsedMqttMessage
from repositories import tag_repo, log_repo

logger = logging.getLogger(__name__)


def process_message(msg: ParsedMqttMessage) -> bool:
    """
    Proses satu pesan MQTT yang sudah di-parse.

    Alur:
      1. Lookup tag dari DB berdasarkan mqtt_topic
      2. Validasi device aktif & tag aktif
      3. Hitung status (NORMAL / WARNING / CRITICAL)
      4. Insert ke logs

    Return True jika berhasil disimpan, False jika skip/error.
    """
    tag_info = tag_repo.get_tag_by_topic(msg.raw_topic)

    if tag_info is None:
        _handle_unknown(msg, "topic tidak ditemukan di tabel tags")
        return False

    if not tag_info["device_aktif"]:
        logger.debug(f"🔕 Device nonaktif, skip | topic={msg.raw_topic}")
        return False

    if not tag_info["tag_aktif"]:
        logger.debug(f"🔕 Tag nonaktif, skip | topic={msg.raw_topic}")
        return False

    status = _compute_status(
        value=msg.value,
        batas_warning=tag_info["batas_warning"],
        batas_critical=tag_info["batas_critical"],
    )

    try:
        log_repo.insert_log(
            device_id=tag_info["device_id"],
            tag_name=tag_info["tag_name"],
            value=msg.value,
            status=status,
            mqtt_topic=msg.raw_topic,
            ts_sensor=msg.ts_sensor,
        )
    except Exception as e:
        logger.error(f"❌ Gagal insert log: {e} | topic={msg.raw_topic}")
        return False

    logger.info(
        f"💾 Log tersimpan | device={tag_info['device_id']} "
        f"tag={tag_info['tag_name']} "
        f"value={msg.value} {tag_info.get('satuan','')} "
        f"status={status}"
    )
    return True


# ── HELPERS ──────────────────────────────────────────────────

def _compute_status(
    value: float,
    batas_warning: Optional[float],
    batas_critical: Optional[float],
) -> str:
    """
    Hitung status berdasarkan nilai dan threshold.
    CRITICAL > WARNING > NORMAL.
    Threshold None berarti tidak ada batas untuk level tersebut.
    """
    if batas_critical is not None and value >= batas_critical:
        return "CRITICAL"
    if batas_warning is not None and value >= batas_warning:
        return "WARNING"
    return "NORMAL"


def _handle_unknown(msg: ParsedMqttMessage, alasan: str) -> None:
    """
    Catat pesan yang tidak dikenal ke tabel unknown_messages.
    Log WARNING agar mudah dimonitor.
    """
    logger.warning(
        f"⚠️  Pesan tidak dikenal | topic={msg.raw_topic} | alasan={alasan}"
    )
    try:
        log_repo.insert_unknown_message(
            mqtt_topic=msg.raw_topic,
            payload_raw=str(msg.value),
            alasan=alasan,
        )
    except Exception as e:
        logger.error(f"❌ Gagal simpan unknown_message: {e}")