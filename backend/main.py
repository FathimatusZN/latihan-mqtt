"""
============================================================
 FILE    : backend/main.py
 PROYEK  : Sistem Monitoring Arus Listrik Mesin Pabrik
 FUNGSI  : 1) Subscribe ke broker MQTT (global + per-device topic)
           2) Parse payload JSON yang diterima
           3) INSERT data ke PostgreSQL
           4) Expose REST API untuk frontend
 JALANKAN: python main.py
============================================================
"""

import json
import os
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.pool
import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional, List

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
load_dotenv()

DB_HOST        = os.getenv("DB_HOST", "localhost")
DB_PORT        = int(os.getenv("DB_PORT", "5432"))
DB_NAME        = os.getenv("DB_NAME", "monitoring_pabrik")
DB_USER        = os.getenv("DB_USER", "postgres")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "password")

MQTT_BROKER    = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC     = os.getenv("MQTT_TOPIC", "pabrik/efortech/mesin/arus")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "efortech-monitor-001")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ============================================================
# DATABASE CONNECTION POOL
# ============================================================
db_pool = None

def init_db_pool():
    global db_pool
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10,
            host=DB_HOST, port=DB_PORT,
            dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
        )
        logger.info(f"✅ Database pool berhasil dibuat → {DB_HOST}:{DB_PORT}/{DB_NAME}")
    except psycopg2.OperationalError as e:
        logger.error(f"❌ Gagal koneksi ke database: {e}")
        raise

def get_db_conn():
    return db_pool.getconn()

def release_db_conn(conn):
    db_pool.putconn(conn)


# ============================================================
# MQTT TOPIC MANAGEMENT
# Kelola set topic yang sedang disubscribe secara dinamis
# ============================================================
_mqtt_client_ref = None          # referensi ke client aktif
_subscribed_topics: set = set()  # topic yang sudah disubscribe

def get_active_topics_from_db() -> set:
    """
    Ambil semua topic unik yang perlu disubscribe:
    - Topic global (dari env) selalu masuk
    - Topic per-mesin dari daftar_mesin.mqtt_topic (jika diisi)
    """
    topics = {MQTT_TOPIC}
    conn = None
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT mqtt_topic
            FROM daftar_mesin
            WHERE aktif = TRUE AND mqtt_topic IS NOT NULL AND mqtt_topic <> ''
        """)
        for row in cur.fetchall():
            topics.add(row[0])
    except Exception as e:
        logger.error(f"❌ Gagal ambil topic dari DB: {e}")
    finally:
        if conn:
            release_db_conn(conn)
    return topics

def sync_subscriptions():
    """
    Bandingkan topic aktif di DB dengan yang sudah disubscribe.
    Subscribe topic baru, unsubscribe topic yang tidak lagi dipakai.
    """
    global _subscribed_topics
    if _mqtt_client_ref is None:
        return

    needed   = get_active_topics_from_db()
    to_add   = needed - _subscribed_topics
    to_remove = _subscribed_topics - needed

    for t in to_add:
        _mqtt_client_ref.subscribe(t, qos=1)
        logger.info(f"📡 Subscribe topic: {t}")

    for t in to_remove:
        _mqtt_client_ref.unsubscribe(t)
        logger.info(f"🔕 Unsubscribe topic: {t}")

    _subscribed_topics = needed


# ============================================================
# SIMPAN DATA KE POSTGRESQL
# ============================================================
def simpan_ke_database(data: dict):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        nama_mesin = data.get("nama_mesin", "Unknown")

        # Lookup konfigurasi dari daftar_mesin (prioritas DB)
        cursor.execute("""
            SELECT batas_arus_max, batas_arus_warning, lokasi
            FROM daftar_mesin
            WHERE nama_mesin = %s AND aktif = TRUE
        """, (nama_mesin,))
        row = cursor.fetchone()

        if row:
            batas_max     = float(row[0])
            batas_warning = float(row[1])
            lokasi        = row[2]
        else:
            batas_max     = float(data.get("batas_arus_max", 20.0))
            batas_warning = batas_max * 0.75
            lokasi        = data.get("lokasi", None)
            logger.warning(f"⚠️  Mesin '{nama_mesin}' tidak ada di daftar_mesin, pakai nilai payload")

        nilai_arus = float(data["nilai_arus"])

        if nilai_arus >= batas_max:
            status = "CRITICAL"
        elif nilai_arus >= batas_warning:
            status = "WARNING"
        else:
            status = "NORMAL"

        cursor.execute("""
            INSERT INTO logs_mesin
                (nama_mesin, nilai_arus, status_mesin, batas_arus_max,
                 lokasi, keterangan, waktu_sensor)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            nama_mesin, nilai_arus, status, batas_max,
            lokasi,
            data.get("keterangan", None),
            data.get("waktu_sensor", None)
        ))
        conn.commit()
        logger.info(f"💾 Data tersimpan | Mesin: {nama_mesin} | Arus: {nilai_arus:.2f}A | Status: {status}")

    except psycopg2.Error as e:
        if conn: conn.rollback()
        logger.error(f"❌ Error database: {e}")
    except (ValueError, KeyError) as e:
        logger.error(f"❌ Data tidak valid: {e} | Payload: {data}")
    finally:
        if conn: release_db_conn(conn)


# ============================================================
# MQTT CALLBACKS
# ============================================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info(f"✅ Terhubung ke MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
        sync_subscriptions()
    else:
        logger.error(f"❌ Gagal konek ke broker. Return code: {rc}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        logger.warning(f"⚠️  Koneksi terputus (rc={rc}). Mencoba reconnect...")

def on_message(client, userdata, msg):
    logger.info(f"📨 Pesan diterima dari topic: {msg.topic}")
    try:
        payload_dict = json.loads(msg.payload.decode("utf-8"))
        if "nama_mesin" not in payload_dict:
            logger.warning("⚠️  Field 'nama_mesin' tidak ditemukan, skip.")
            return
        if "nilai_arus" not in payload_dict:
            logger.warning("⚠️  Field 'nilai_arus' tidak ditemukan, skip.")
            return
        simpan_ke_database(payload_dict)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Payload bukan JSON valid: {e}")
    except Exception as e:
        logger.error(f"❌ Error tidak terduga: {e}")


# ============================================================
# SETUP MQTT CLIENT
# ============================================================
def setup_mqtt_client() -> mqtt.Client:
    global _mqtt_client_ref
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    try:
        logger.info(f"🔌 Menghubungkan ke broker {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        _mqtt_client_ref = client
        return client
    except Exception as e:
        logger.error(f"❌ Gagal setup MQTT client: {e}")
        raise


# ============================================================
# PYDANTIC MODELS
# ============================================================
class LogMesin(BaseModel):
    id: int
    nama_mesin: str
    nilai_arus: float
    status_mesin: str
    lokasi: Optional[str]
    keterangan: Optional[str]
    waktu_simpan: datetime

class MesinCreate(BaseModel):
    nama_mesin: str
    nama_display: Optional[str] = None
    tipe_mesin: Optional[str] = None
    lokasi: Optional[str] = None
    batas_arus_max: float = 20.0
    batas_arus_warning: float = 15.0
    mqtt_topic: Optional[str] = None
    aktif: bool = True

class MesinUpdate(BaseModel):
    nama_display: Optional[str] = None
    tipe_mesin: Optional[str] = None
    lokasi: Optional[str] = None
    batas_arus_max: Optional[float] = None
    batas_arus_warning: Optional[float] = None
    mqtt_topic: Optional[str] = None
    aktif: Optional[bool] = None

class MqttTopicUpdate(BaseModel):
    mqtt_topic: Optional[str] = None   # None / "" = pakai topic global


# ============================================================
# FASTAPI APP
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Memulai aplikasi Monitoring Arus Listrik...")
    init_db_pool()
    app.state.mqtt_client = setup_mqtt_client()
    yield
    logger.info("🛑 Menghentikan aplikasi...")
    app.state.mqtt_client.loop_stop()
    app.state.mqtt_client.disconnect()
    db_pool.closeall()

app = FastAPI(
    title="API Monitoring Arus Listrik Mesin Pabrik",
    description="REST API untuk dashboard monitoring dan konfigurasi perangkat",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ── HEALTH ────────────────────────────────────────────────
@app.get("/", summary="Health check")
def root():
    return {"status": "ok", "service": "Monitoring Arus Listrik Mesin Pabrik"}


@app.get("/status", summary="Status koneksi MQTT & Database")
def get_status():
    return {
        "mqtt_broker": MQTT_BROKER,
        "mqtt_topic_global": MQTT_TOPIC,
        "database": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "service": "running"
    }


# ── LOGS ──────────────────────────────────────────────────
@app.get("/logs", summary="Ambil log pembacaan arus terbaru")
def get_logs(
    limit: int = Query(default=50, ge=1, le=500),
    nama_mesin: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None)
):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        query  = """
            SELECT id, nama_mesin, nilai_arus, status_mesin,
                   lokasi, keterangan, waktu_simpan
            FROM logs_mesin WHERE 1=1
        """
        params = []
        if nama_mesin:
            query += " AND nama_mesin = %s"
            params.append(nama_mesin)
        if status:
            query += " AND status_mesin = %s"
            params.append(status.upper())
        query += " ORDER BY waktu_simpan DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        columns = ["id", "nama_mesin", "nilai_arus", "status_mesin",
                   "lokasi", "keterangan", "waktu_simpan"]
        return {"total": len(rows), "data": [dict(zip(columns, r)) for r in rows]}

    except psycopg2.Error as e:
        logger.error(f"❌ Error query: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


# ── STATISTIK ─────────────────────────────────────────────
@app.get("/statistik", summary="Statistik ringkasan per mesin (24 jam)")
def get_statistik():
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT nama_mesin,
                   COUNT(*) AS total_pembacaan,
                   ROUND(AVG(nilai_arus)::NUMERIC, 2) AS rata_rata_arus,
                   ROUND(MAX(nilai_arus)::NUMERIC, 2) AS puncak_arus,
                   COUNT(*) FILTER (WHERE status_mesin = 'WARNING')  AS total_warning,
                   COUNT(*) FILTER (WHERE status_mesin = 'CRITICAL') AS total_critical,
                   MAX(waktu_simpan) AS terakhir_update
            FROM logs_mesin
            WHERE waktu_simpan >= NOW() - INTERVAL '24 hours'
            GROUP BY nama_mesin ORDER BY nama_mesin
        """)
        rows = cursor.fetchall()
        columns = ["nama_mesin","total_pembacaan","rata_rata_arus",
                   "puncak_arus","total_warning","total_critical","terakhir_update"]
        return {"periode": "24 jam terakhir", "data": [dict(zip(columns, r)) for r in rows]}
    except psycopg2.Error:
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


# ── MESIN — LIST & STATUS ──────────────────────────────────
@app.get("/mesin", summary="Daftar semua mesin")
def get_daftar_mesin():
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT nama_mesin, nama_display, tipe_mesin, lokasi,
                   batas_arus_max, batas_arus_warning, mqtt_topic, aktif
            FROM daftar_mesin ORDER BY nama_mesin
        """)
        rows = cursor.fetchall()
        columns = ["nama_mesin","nama_display","tipe_mesin","lokasi",
                   "batas_arus_max","batas_arus_warning","mqtt_topic","aktif"]
        return {"total": len(rows), "data": [dict(zip(columns, r)) for r in rows]}
    except psycopg2.Error:
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.get("/mesin/status", summary="Status terkini semua mesin aktif")
def get_status_mesin():
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                dm.nama_mesin,
                COALESCE(dm.nama_display, REPLACE(dm.nama_mesin, '_', ' ')) AS nama_display,
                dm.tipe_mesin,
                dm.lokasi,
                dm.batas_arus_max,
                dm.batas_arus_warning,
                dm.mqtt_topic,
                latest.nilai_arus    AS nilai_arus_terkini,
                latest.status_mesin  AS status_terkini,
                latest.waktu_simpan  AS waktu_terkini,
                stat.total_pembacaan,
                stat.rata_rata_arus,
                stat.puncak_arus,
                stat.total_warning,
                stat.total_critical
            FROM daftar_mesin dm
            LEFT JOIN LATERAL (
                SELECT nilai_arus, status_mesin, waktu_simpan
                FROM logs_mesin
                WHERE nama_mesin = dm.nama_mesin
                ORDER BY waktu_simpan DESC LIMIT 1
            ) latest ON TRUE
            LEFT JOIN (
                SELECT
                    nama_mesin,
                    COUNT(*)                              AS total_pembacaan,
                    ROUND(AVG(nilai_arus)::NUMERIC, 2)   AS rata_rata_arus,
                    ROUND(MAX(nilai_arus)::NUMERIC, 2)   AS puncak_arus,
                    COUNT(*) FILTER (WHERE status_mesin = 'WARNING')  AS total_warning,
                    COUNT(*) FILTER (WHERE status_mesin = 'CRITICAL') AS total_critical
                FROM logs_mesin
                WHERE waktu_simpan >= NOW() - INTERVAL '24 hours'
                GROUP BY nama_mesin
            ) stat ON stat.nama_mesin = dm.nama_mesin
            WHERE dm.aktif = TRUE
            ORDER BY dm.nama_mesin
        """)
        rows = cursor.fetchall()
        columns = [
            "nama_mesin","nama_display","tipe_mesin","lokasi",
            "batas_arus_max","batas_arus_warning","mqtt_topic",
            "nilai_arus_terkini","status_terkini","waktu_terkini",
            "total_pembacaan","rata_rata_arus","puncak_arus",
            "total_warning","total_critical"
        ]
        result = [dict(zip(columns, r)) for r in rows]
        for r in result:
            if r["waktu_terkini"]:
                r["waktu_terkini"] = r["waktu_terkini"].isoformat()
        return {"total": len(result), "data": result}
    except psycopg2.Error as e:
        logger.error(f"❌ Error query status mesin: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


# ── MESIN — CRUD ──────────────────────────────────────────
@app.post("/mesin", summary="Tambah mesin baru")
def tambah_mesin(body: MesinCreate):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        display = body.nama_display or body.nama_mesin.replace("_", " ")
        cursor.execute("""
            INSERT INTO daftar_mesin
                (nama_mesin, nama_display, tipe_mesin, lokasi,
                 batas_arus_max, batas_arus_warning, mqtt_topic, aktif)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (body.nama_mesin, display, body.tipe_mesin, body.lokasi,
              body.batas_arus_max, body.batas_arus_warning,
              body.mqtt_topic or None, body.aktif))
        new_id = cursor.fetchone()[0]
        conn.commit()
        sync_subscriptions()   # subscribe topic baru jika ada
        return {"success": True, "id": new_id, "nama_mesin": body.nama_mesin}
    except psycopg2.errors.UniqueViolation:
        if conn: conn.rollback()
        raise HTTPException(status_code=409, detail=f"Mesin '{body.nama_mesin}' sudah ada")
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.put("/mesin/{nama_mesin}", summary="Update konfigurasi mesin")
def update_mesin(nama_mesin: str, body: MesinUpdate):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        fields, values = [], []
        if body.nama_display is not None:
            fields.append("nama_display = %s");       values.append(body.nama_display)
        if body.tipe_mesin is not None:
            fields.append("tipe_mesin = %s");         values.append(body.tipe_mesin)
        if body.lokasi is not None:
            fields.append("lokasi = %s");             values.append(body.lokasi)
        if body.batas_arus_max is not None:
            fields.append("batas_arus_max = %s");     values.append(body.batas_arus_max)
        if body.batas_arus_warning is not None:
            fields.append("batas_arus_warning = %s"); values.append(body.batas_arus_warning)
        if body.mqtt_topic is not None:
            # Simpan None kalau string kosong (berarti pakai global)
            fields.append("mqtt_topic = %s");         values.append(body.mqtt_topic or None)
        if body.aktif is not None:
            fields.append("aktif = %s");              values.append(body.aktif)

        if not fields:
            raise HTTPException(status_code=400, detail="Tidak ada field yang diupdate")

        values.append(nama_mesin)
        cursor.execute(
            f"UPDATE daftar_mesin SET {', '.join(fields)} WHERE nama_mesin = %s",
            values
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Mesin '{nama_mesin}' tidak ditemukan")
        conn.commit()
        sync_subscriptions()   # sinkronkan topic setelah update
        return {"success": True, "nama_mesin": nama_mesin}
    except HTTPException:
        raise
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.delete("/mesin/{nama_mesin}", summary="Hapus mesin")
def hapus_mesin(nama_mesin: str):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM daftar_mesin WHERE nama_mesin = %s", (nama_mesin,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Mesin '{nama_mesin}' tidak ditemukan")
        conn.commit()
        sync_subscriptions()   # unsubscribe topic yang tidak lagi dipakai
        return {"success": True, "deleted": nama_mesin}
    except HTTPException:
        raise
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


# ── MQTT CONFIG ENDPOINTS ──────────────────────────────────
@app.get("/mqtt/info", summary="Info broker dan topic aktif")
def get_mqtt_info():
    """
    Kembalikan info broker global dan daftar topic yang sedang disubscribe,
    beserta ringkasan per-topic (berapa mesin, berapa aktif).
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        # Ringkasan per topic
        cursor.execute("""
            SELECT
                COALESCE(mqtt_topic, %s) AS topic_efektif,
                COUNT(*)                 AS total_mesin,
                COUNT(*) FILTER (WHERE aktif = TRUE) AS mesin_aktif
            FROM daftar_mesin
            GROUP BY COALESCE(mqtt_topic, %s)
            ORDER BY topic_efektif
        """, (MQTT_TOPIC, MQTT_TOPIC))
        rows = cursor.fetchall()
        topic_summary = [
            {"topic": r[0], "total_mesin": r[1], "mesin_aktif": r[2]}
            for r in rows
        ]

        # Statistik pesan 24 jam terakhir per topic
        # (kita join dengan daftar_mesin untuk tahu topic efektifnya)
        cursor.execute("""
            SELECT
                COALESCE(dm.mqtt_topic, %s) AS topic_efektif,
                COUNT(l.id)                 AS total_pesan_24j
            FROM logs_mesin l
            JOIN daftar_mesin dm ON dm.nama_mesin = l.nama_mesin
            WHERE l.waktu_simpan >= NOW() - INTERVAL '24 hours'
            GROUP BY COALESCE(dm.mqtt_topic, %s)
        """, (MQTT_TOPIC, MQTT_TOPIC))
        msg_rows = cursor.fetchall()
        msg_map = {r[0]: r[1] for r in msg_rows}

        for ts in topic_summary:
            ts["pesan_24j"] = msg_map.get(ts["topic"], 0)

        return {
            "broker": {
                "host":         MQTT_BROKER,
                "port":         MQTT_PORT,
                "client_id":    MQTT_CLIENT_ID,
                "topic_global": MQTT_TOPIC,
            },
            "subscribed_topics": sorted(list(_subscribed_topics)),
            "topic_summary":     topic_summary,
        }
    except psycopg2.Error as e:
        logger.error(f"❌ Error mqtt/info: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.get("/mqtt/mesin", summary="Daftar mesin beserta topic efektif")
def get_mqtt_mesin():
    """
    Kembalikan semua mesin (aktif maupun tidak) beserta topic efektif
    yang digunakan — topic custom jika diisi, topic global jika tidak.
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                nama_mesin,
                COALESCE(nama_display, REPLACE(nama_mesin, '_', ' ')) AS nama_display,
                aktif,
                mqtt_topic                     AS topic_custom,
                COALESCE(mqtt_topic, %s)       AS topic_efektif
            FROM daftar_mesin
            ORDER BY nama_mesin
        """, (MQTT_TOPIC,))
        rows = cursor.fetchall()
        columns = ["nama_mesin", "nama_display", "aktif", "topic_custom", "topic_efektif"]
        return {"global_topic": MQTT_TOPIC, "data": [dict(zip(columns, r)) for r in rows]}
    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.put("/mqtt/mesin/{nama_mesin}/topic", summary="Set topic MQTT untuk satu mesin")
def set_topic_mesin(nama_mesin: str, body: MqttTopicUpdate):
    """
    Set atau hapus topic custom untuk mesin tertentu.
    Kirim mqtt_topic = null / "" untuk kembali ke topic global.
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        topic_val = body.mqtt_topic.strip() if body.mqtt_topic else None
        cursor.execute(
            "UPDATE daftar_mesin SET mqtt_topic = %s WHERE nama_mesin = %s",
            (topic_val or None, nama_mesin)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Mesin '{nama_mesin}' tidak ditemukan")
        conn.commit()
        sync_subscriptions()
        return {
            "success":      True,
            "nama_mesin":   nama_mesin,
            "mqtt_topic":   topic_val,
            "menggunakan":  topic_val or MQTT_TOPIC
        }
    except HTTPException:
        raise
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)


@app.post("/mqtt/sync", summary="Paksa sinkronisasi ulang topic subscriptions")
def force_sync_topics():
    """Trigger manual sync topic MQTT dari DB ke broker."""
    before = sorted(list(_subscribed_topics))
    sync_subscriptions()
    after  = sorted(list(_subscribed_topics))
    return {"success": True, "before": before, "after": after}


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  SISTEM MONITORING ARUS LISTRIK MESIN PABRIK")
    logger.info("=" * 60)
    logger.info(f"  MQTT Broker : {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"  MQTT Topic  : {MQTT_TOPIC}")
    logger.info(f"  Database    : {DB_HOST}:{DB_PORT}/{DB_NAME}")
    logger.info(f"  API         : http://{API_HOST}:{API_PORT}")
    logger.info(f"  API Docs    : http://localhost:{API_PORT}/docs")
    logger.info("=" * 60)

    uvicorn.run("main:app", host=API_HOST, port=API_PORT,
                reload=False, log_level="info")