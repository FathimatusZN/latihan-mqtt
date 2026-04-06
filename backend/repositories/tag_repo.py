"""
============================================================
 FILE    : backend/repositories/tag_repo.py
 FUNGSI  : Repository untuk tabel tags & topic-to-tag mapping
           Semua SQL terkait tags ada di sini — tidak tersebar
============================================================
"""

from __future__ import annotations
import logging
from typing import Optional
from contextlib import contextmanager

from repositories.db import get_conn, release_conn

logger = logging.getLogger(__name__)


@contextmanager
def _conn_ctx():
    """Context manager: ambil koneksi → yield → kembalikan."""
    conn = get_conn()
    try:
        yield conn
    finally:
        release_conn(conn)


# ── TAG LOOKUP (paling sering dipanggil oleh consumer) ──────

def get_tag_by_topic(mqtt_topic: str) -> Optional[dict]:
    """
    Lookup tag berdasarkan mqtt_topic yang diterima.
    Return dict dengan info tag + device, atau None jika tidak ditemukan.

    Query ini adalah inti dari topic-based routing:
    topic → (device_id, tag_name, threshold)
    """
    sql = """
        SELECT
            t.device_id,
            t.tag_name,
            t.satuan,
            t.batas_warning,
            t.batas_critical,
            d.aktif        AS device_aktif,
            t.aktif        AS tag_aktif,
            d.factory_id
        FROM tags t
        JOIN devices d ON d.device_id = t.device_id
        WHERE t.mqtt_topic = %s
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (mqtt_topic,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [
            "device_id", "tag_name", "satuan",
            "batas_warning", "batas_critical",
            "device_aktif", "tag_aktif", "factory_id",
        ]
        return dict(zip(cols, row))


def get_all_active_topics() -> set[str]:
    """
    Ambil semua mqtt_topic dari tags yang aktif & device-nya aktif.
    Dipakai saat sync MQTT subscriptions.
    """
    sql = """
        SELECT t.mqtt_topic
        FROM tags t
        JOIN devices d ON d.device_id = t.device_id
        WHERE t.aktif = TRUE AND d.aktif = TRUE
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        return {row[0] for row in cur.fetchall()}


def list_tags(device_id: Optional[str] = None) -> list[dict]:
    """List semua tag, opsional filter per device."""
    sql = """
        SELECT id, device_id, tag_name, satuan, deskripsi,
               mqtt_topic, batas_warning, batas_critical, aktif
        FROM tags
        WHERE 1=1
    """
    params = []
    if device_id:
        sql += " AND device_id = %s"
        params.append(device_id)
    sql += " ORDER BY device_id, tag_name"

    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [
            "id", "device_id", "tag_name", "satuan", "deskripsi",
            "mqtt_topic", "batas_warning", "batas_critical", "aktif",
        ]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_tag(device_id: str, data: dict) -> int:
    """
    Buat tag baru. mqtt_topic di-generate otomatis dari
    factory_id + device_id + tag_name.
    Return: id tag baru.
    """
    # Ambil factory_id dari device
    factory_id = _get_factory_id(device_id)

    tag_name   = data["tag_name"]
    mqtt_topic = f"pabrik/{factory_id}/{device_id}/{tag_name}"

    sql = """
        INSERT INTO tags
            (device_id, tag_name, satuan, deskripsi, mqtt_topic,
             batas_warning, batas_critical, aktif)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (
            device_id,
            tag_name,
            data.get("satuan"),
            data.get("deskripsi"),
            mqtt_topic,
            data.get("batas_warning"),
            data.get("batas_critical"),
            data.get("aktif", True),
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def update_tag(device_id: str, tag_name: str, data: dict) -> bool:
    """Update tag. Return True jika berhasil."""
    fields, values = [], []
    for col in ("satuan", "deskripsi", "batas_warning", "batas_critical", "aktif"):
        if col in data and data[col] is not None:
            fields.append(f"{col} = %s")
            values.append(data[col])

    if not fields:
        return False

    values.extend([device_id, tag_name])
    sql = f"""
        UPDATE tags SET {', '.join(fields)}
        WHERE device_id = %s AND tag_name = %s
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


def delete_tag(device_id: str, tag_name: str) -> bool:
    sql = "DELETE FROM tags WHERE device_id = %s AND tag_name = %s"
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (device_id, tag_name))
        conn.commit()
        return cur.rowcount > 0


# ── HELPERS ──────────────────────────────────────────────────

def _get_factory_id(device_id: str) -> str:
    sql = "SELECT factory_id FROM devices WHERE device_id = %s"
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (device_id,))
        row = cur.fetchone()
        return row[0] if row else "efortech"