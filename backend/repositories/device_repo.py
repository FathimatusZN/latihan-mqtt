"""
============================================================
 FILE    : backend/repositories/device_repo.py
 FUNGSI  : Repository untuk tabel devices
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
    conn = get_conn()
    try:
        yield conn
    finally:
        release_conn(conn)


def list_devices(aktif_only: bool = False) -> list[dict]:
    sql = """
        SELECT device_id, nama_display, tipe, lokasi, factory_id, aktif, dibuat_pada
        FROM devices
        WHERE 1=1
    """
    params = []
    if aktif_only:
        sql += " AND aktif = TRUE"
    sql += " ORDER BY device_id"

    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = ["device_id", "nama_display", "tipe", "lokasi",
                "factory_id", "aktif", "dibuat_pada"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_device(device_id: str) -> Optional[dict]:
    sql = """
        SELECT device_id, nama_display, tipe, lokasi, factory_id, aktif, dibuat_pada
        FROM devices WHERE device_id = %s
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (device_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = ["device_id", "nama_display", "tipe", "lokasi",
                "factory_id", "aktif", "dibuat_pada"]
        return dict(zip(cols, row))


def create_device(data: dict) -> str:
    """Buat device baru. Return device_id."""
    display = data.get("nama_display") or data["device_id"].replace("_", " ")
    sql = """
        INSERT INTO devices
            (device_id, nama_display, tipe, lokasi, factory_id, aktif)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING device_id
    """
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (
            data["device_id"],
            display,
            data.get("tipe"),
            data.get("lokasi"),
            data.get("factory_id", "efortech"),
            data.get("aktif", True),
        ))
        new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def update_device(device_id: str, data: dict) -> bool:
    fields, values = [], []
    for col in ("nama_display", "tipe", "lokasi", "factory_id", "aktif"):
        if col in data and data[col] is not None:
            fields.append(f"{col} = %s")
            values.append(data[col])
    fields.append("diupdate_pada = NOW()")

    if len(fields) == 1:  # hanya diupdate_pada
        return False

    values.append(device_id)
    sql = f"UPDATE devices SET {', '.join(fields)} WHERE device_id = %s"
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


def delete_device(device_id: str) -> bool:
    sql = "DELETE FROM devices WHERE device_id = %s"
    with _conn_ctx() as conn:
        cur = conn.cursor()
        cur.execute(sql, (device_id,))
        conn.commit()
        return cur.rowcount > 0