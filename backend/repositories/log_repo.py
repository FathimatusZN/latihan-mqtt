"""
============================================================
 FILE    : backend/repositories/log_repo.py
 FUNGSI  : Repository untuk tabel logs (time-series) dan
           unknown_messages (audit trail)
============================================================
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional
from contextlib import contextmanager

from repositories.db import get_conn, release_conn

logger = logging.getLogger(__name__)


@contextmanager
def _conn_ctx():
    conn = get_conn()
    try:
        yield conn
    finally:
        release_conn(conn)


# ── LOGS ─────────────────────────────────────────────────────

def insert_log(
    device_id: str,
    tag_name:  str,
    value:     float,
    status:    str,
    mqtt_topic: Optional[str] = None,
    ts_sensor:  Optional[datetime] = None,
) -> None:
    """Insert satu baris log. Dipanggil dari ingestion service."""
    sql = """
        INSERT INTO logs
            (device_id, tag_name, value, status, mqtt_topic, ts_sensor)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (device_id, tag_name, value, status, mqtt_topic, ts_sensor))
        conn.commit()


def query_logs(
    device_id:  Optional[str] = None,
    tag_name:   Optional[str] = None,
    status:     Optional[str] = None,
    limit:      int = 100,
) -> list[dict]:
    """Query logs dengan filter opsional, urut terbaru dulu."""
    sql = """
        SELECT id, device_id, tag_name, value, status,
               mqtt_topic, ts_sensor, ts_simpan
        FROM logs WHERE 1=1
    """
    params = []
    if device_id:
        sql += " AND device_id = %s";  params.append(device_id)
    if tag_name:
        sql += " AND tag_name = %s";   params.append(tag_name)
    if status:
        sql += " AND status = %s";     params.append(status.upper())
    sql += " ORDER BY ts_simpan DESC LIMIT %s"
    params.append(limit)

    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = ["id", "device_id", "tag_name", "value", "status",
                "mqtt_topic", "ts_sensor", "ts_simpan"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_device_status() -> list[dict]:
    """
    Status terkini semua device aktif beserta semua tag-nya.
    LEFT JOIN ke v_tag_status untuk mendapat last value per tag.
    """
    sql = """
        SELECT
            d.device_id,
            d.nama_display,
            d.lokasi,
            d.factory_id,
            d.aktif,
            t.tag_name,
            t.satuan,
            t.deskripsi       AS tag_deskripsi,
            t.batas_warning,
            t.batas_critical,
            t.aktif           AS tag_aktif,
            latest.value      AS nilai_terkini,
            latest.status     AS status_terkini,
            latest.ts_sensor,
            latest.ts_simpan  AS terakhir_update,
            stat.total_pembacaan,
            stat.rata_rata,
            stat.nilai_max,
            stat.total_warning,
            stat.total_critical
        FROM devices d
        JOIN tags t ON t.device_id = d.device_id
        LEFT JOIN LATERAL (
            SELECT value, status, ts_sensor, ts_simpan
            FROM logs
            WHERE device_id = d.device_id AND tag_name = t.tag_name
            ORDER BY ts_simpan DESC LIMIT 1
        ) latest ON TRUE
        LEFT JOIN (
            SELECT
                device_id, tag_name,
                COUNT(*)                              AS total_pembacaan,
                ROUND(AVG(value)::NUMERIC, 4)         AS rata_rata,
                ROUND(MAX(value)::NUMERIC, 4)         AS nilai_max,
                COUNT(*) FILTER (WHERE status = 'WARNING')  AS total_warning,
                COUNT(*) FILTER (WHERE status = 'CRITICAL') AS total_critical
            FROM logs
            WHERE ts_simpan >= NOW() - INTERVAL '24 hours'
            GROUP BY device_id, tag_name
        ) stat ON stat.device_id = d.device_id AND stat.tag_name = t.tag_name
        WHERE d.aktif = TRUE AND t.aktif = TRUE
        ORDER BY d.device_id, t.tag_name
    """
    cols = [
        "device_id", "nama_display", "lokasi", "factory_id", "aktif",
        "tag_name", "satuan", "tag_deskripsi", "batas_warning", "batas_critical",
        "tag_aktif", "nilai_terkini", "status_terkini", "ts_sensor", "terakhir_update",
        "total_pembacaan", "rata_rata", "nilai_max", "total_warning", "total_critical",
    ]
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Serialize datetime
    for r in rows:
        for key in ("ts_sensor", "terakhir_update"):
            if r[key]:
                r[key] = r[key].isoformat()
    return rows


def get_statistik_24h() -> list[dict]:
    """Statistik per device+tag untuk 24 jam terakhir."""
    sql = """
        SELECT
            device_id, tag_name,
            COUNT(*)                              AS total_pembacaan,
            ROUND(AVG(value)::NUMERIC, 4)         AS rata_rata,
            ROUND(MAX(value)::NUMERIC, 4)         AS nilai_max,
            ROUND(MIN(value)::NUMERIC, 4)         AS nilai_min,
            COUNT(*) FILTER (WHERE status = 'WARNING')  AS total_warning,
            COUNT(*) FILTER (WHERE status = 'CRITICAL') AS total_critical,
            MAX(ts_simpan)                        AS terakhir_update
        FROM logs
        WHERE ts_simpan >= NOW() - INTERVAL '24 hours'
        GROUP BY device_id, tag_name
        ORDER BY device_id, tag_name
    """
    cols = [
        "device_id", "tag_name", "total_pembacaan", "rata_rata",
        "nilai_max", "nilai_min", "total_warning", "total_critical",
        "terakhir_update",
    ]
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("terakhir_update"):
            r["terakhir_update"] = r["terakhir_update"].isoformat()
    return rows


# ── UNKNOWN MESSAGES ──────────────────────────────────────────

def insert_unknown_message(
    mqtt_topic:  str,
    payload_raw: Optional[str],
    alasan:      str,
) -> None:
    """Simpan pesan yang tidak bisa dipetakan ke tag manapun."""
    sql = """
        INSERT INTO unknown_messages (mqtt_topic, payload_raw, alasan)
        VALUES (%s, %s, %s)
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (mqtt_topic, payload_raw, alasan))
        conn.commit()


def query_unknown_messages(limit: int = 50) -> list[dict]:
    sql = """
        SELECT id, mqtt_topic, payload_raw, alasan, ts_terima
        FROM unknown_messages
        ORDER BY ts_terima DESC
        LIMIT %s
    """
    cols = ["id", "mqtt_topic", "payload_raw", "alasan", "ts_terima"]
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (limit,))
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        if r.get("ts_terima"):
            r["ts_terima"] = r["ts_terima"].isoformat()
    return rows