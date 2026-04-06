"""
============================================================
 FILE    : backend/repositories/db.py
 FUNGSI  : Database connection pool management
           Satu tempat untuk semua koneksi DB — tidak ada
           psycopg2 import di file lain selain repository layer
============================================================
"""

import logging
import psycopg2
import psycopg2.pool
import psycopg2.extras

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    minconn: int = 2,
    maxconn: int = 10,
) -> None:
    """Inisialisasi connection pool. Dipanggil sekali saat startup."""
    global _pool
    _pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )
    logger.info(f"✅ DB pool ready → {host}:{port}/{dbname}")


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("🛑 DB pool ditutup")


def get_conn():
    """Ambil koneksi dari pool."""
    if _pool is None:
        raise RuntimeError("DB pool belum diinisialisasi")
    return _pool.getconn()


def release_conn(conn) -> None:
    """Kembalikan koneksi ke pool."""
    if _pool and conn:
        _pool.putconn(conn)