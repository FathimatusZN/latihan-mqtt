"""
============================================================
 FILE    : backend/main.py
 PROYEK  : Sistem Monitoring Arus Listrik Mesin Pabrik
 FUNGSI  : 1) Subscribe ke broker MQTT
           2) Parse payload JSON yang diterima
           3) INSERT data ke PostgreSQL
           4) Expose REST API untuk frontend
 JALANKAN: python main.py
============================================================
"""

import json
import os
import threading
import time
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
from pydantic import BaseModel, Field
from typing import Optional, List

# ============================================================
# KONFIGURASI LOGGING
# Agar output di terminal lebih rapi dan informatif
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ============================================================
# LOAD ENVIRONMENT VARIABLES dari file .env
# ============================================================
load_dotenv()  # Membaca semua variabel dari file .env

# Konfigurasi Database
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "5432"))
DB_NAME     = os.getenv("DB_NAME", "monitoring_pabrik")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# Konfigurasi MQTT Broker
MQTT_BROKER    = os.getenv("MQTT_BROKER", "broker.hivemq.com")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC     = os.getenv("MQTT_TOPIC", "pabrik/efortech/mesin/arus")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "efortech-monitor-001")

# Konfigurasi API
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))


# ============================================================
# DATABASE CONNECTION POOL
# Pool = kumpulan koneksi yang bisa dipakai ulang (efisien)
# Tanpa pool: setiap pesan MQTT buka-tutup koneksi → lambat
# ============================================================
db_pool = None

def init_db_pool():
    """Inisialisasi connection pool ke PostgreSQL."""
    global db_pool
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,   # Minimal 2 koneksi siap standby
            maxconn=10,  # Maksimal 10 koneksi bersamaan
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        logger.info(f"✅ Database pool berhasil dibuat → {DB_HOST}:{DB_PORT}/{DB_NAME}")
    except psycopg2.OperationalError as e:
        logger.error(f"❌ Gagal koneksi ke database: {e}")
        raise


def get_db_conn():
    """Ambil satu koneksi dari pool."""
    return db_pool.getconn()


def release_db_conn(conn):
    """Kembalikan koneksi ke pool setelah selesai dipakai."""
    db_pool.putconn(conn)


# ============================================================
# FUNGSI UTAMA: SIMPAN DATA KE POSTGRESQL
# Dipanggil setiap kali pesan MQTT diterima
# ============================================================
def simpan_ke_database(data: dict):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        nama_mesin = data.get("nama_mesin", "Unknown")

        # ── LOOKUP konfigurasi dari daftar_mesin ──────────────
        # Prioritas: ambil dari DB, payload hanya fallback
        cursor.execute("""
            SELECT batas_arus_max, batas_arus_warning, lokasi
            FROM daftar_mesin
            WHERE nama_mesin = %s AND aktif = TRUE
        """, (nama_mesin,))
        row = cursor.fetchone()

        if row:
            batas_max     = float(row[0])
            batas_warning = float(row[1])
            lokasi        = row[2]  # selalu dari DB
        else:
            # Mesin tidak terdaftar — pakai nilai dari payload sebagai fallback
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

        query = """
            INSERT INTO logs_mesin
                (nama_mesin, nilai_arus, status_mesin, batas_arus_max,
                 lokasi, keterangan, waktu_sensor)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            nama_mesin,
            nilai_arus,
            status,
            batas_max,
            lokasi,                         
            data.get("keterangan", None),
            data.get("waktu_sensor", None)
        )

        cursor.execute(query, values)
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
# MQTT CALLBACK FUNCTIONS
# Fungsi-fungsi ini otomatis dipanggil oleh library paho-mqtt
# berdasarkan event yang terjadi
# ============================================================

def on_connect(client, userdata, flags, rc):
    """
    Dipanggil saat berhasil/gagal terhubung ke broker MQTT.
    rc = Return Code:
      0 = berhasil
      1 = protocol version salah
      2 = client ID tidak valid
      3 = broker tidak tersedia
      4 = username/password salah
      5 = tidak diizinkan
    """
    if rc == 0:
        logger.info(f"✅ Terhubung ke MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
        # Subscribe ke topic setelah berhasil connect
        # QoS 1 = pesan dijamin terkirim minimal sekali
        client.subscribe(MQTT_TOPIC, qos=1)
        logger.info(f"📡 Listening pada topic: {MQTT_TOPIC}")
    else:
        logger.error(f"❌ Gagal konek ke broker. Return code: {rc}")


def on_disconnect(client, userdata, rc):
    """
    Dipanggil saat koneksi ke broker terputus.
    rc = 0 artinya disconnect disengaja, selain 0 = tidak sengaja.
    """
    if rc != 0:
        logger.warning(f"⚠️  Koneksi terputus (rc={rc}). Mencoba reconnect...")


def on_message(client, userdata, msg):
    """
    Dipanggil setiap kali ada pesan masuk dari broker.
    msg.topic   = nama topic
    msg.payload = isi pesan dalam format bytes
    """
    logger.info(f"📨 Pesan diterima dari topic: {msg.topic}")

    try:
        # Decode bytes → string, lalu parse string → dictionary Python
        payload_str  = msg.payload.decode("utf-8")
        payload_dict = json.loads(payload_str)

        logger.debug(f"   Payload: {payload_dict}")

        # Validasi field wajib
        if "nama_mesin" not in payload_dict:
            logger.warning("⚠️  Field 'nama_mesin' tidak ditemukan, skip.")
            return
        if "nilai_arus" not in payload_dict:
            logger.warning("⚠️  Field 'nilai_arus' tidak ditemukan, skip.")
            return

        # Simpan ke database
        simpan_ke_database(payload_dict)

    except json.JSONDecodeError as e:
        # Payload bukan format JSON yang valid
        logger.error(f"❌ Payload bukan JSON valid: {e}")
        logger.error(f"   Raw payload: {msg.payload}")

    except Exception as e:
        logger.error(f"❌ Error tidak terduga saat proses pesan: {e}")


def on_log(client, userdata, level, buf):
    """
    Opsional: Log internal dari library paho-mqtt.
    Dinonaktifkan default untuk menghindari log terlalu banyak.
    Uncomment baris di setup_mqtt_client() jika mau debug mendalam.
    """
    pass  # logger.debug(f"[MQTT Internal] {buf}")


# ============================================================
# SETUP MQTT CLIENT
# ============================================================
def setup_mqtt_client() -> mqtt.Client:
    """Buat dan konfigurasi MQTT client, lalu mulai loop."""

    # Buat instance client dengan ID unik
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)

    # Daftarkan callback functions
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    # client.on_log = on_log  # Uncomment untuk debug detail

    # Set keep-alive: kirim ping ke broker setiap 60 detik
    # Ini menjaga koneksi tetap hidup saat tidak ada pesan
    try:
        logger.info(f"🔌 Menghubungkan ke broker {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

        # Mulai loop di thread terpisah agar tidak blocking FastAPI
        # loop_start() = non-blocking, berjalan di background thread
        client.loop_start()

        return client

    except Exception as e:
        logger.error(f"❌ Gagal setup MQTT client: {e}")
        raise


# ============================================================
# FASTAPI — REST API UNTUK FRONTEND
# ============================================================

# Definisi model response menggunakan Pydantic
class LogMesin(BaseModel):
    id: int
    nama_mesin: str
    nilai_arus: float
    status_mesin: str
    lokasi: Optional[str]
    keterangan: Optional[str]
    waktu_simpan: datetime

class StatusResponse(BaseModel):
    mqtt_connected: bool
    broker: str
    topic: str
    database: str

# Inisialisasi app FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: setup saat startup, cleanup saat shutdown."""
    # === STARTUP ===
    logger.info("🚀 Memulai aplikasi Monitoring Arus Listrik...")
    init_db_pool()          # Buat connection pool ke PostgreSQL
    app.state.mqtt_client = setup_mqtt_client()  # Hubungkan ke MQTT broker
    yield
    # === SHUTDOWN ===
    logger.info("🛑 Menghentikan aplikasi...")
    app.state.mqtt_client.loop_stop()   # Hentikan MQTT loop
    app.state.mqtt_client.disconnect()  # Putuskan koneksi ke broker
    db_pool.closeall()                  # Tutup semua koneksi database

app = FastAPI(
    title="API Monitoring Arus Listrik Mesin Pabrik",
    description="REST API untuk membaca data dari PostgreSQL dan dikonsumsi oleh Frontend Dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware — izinkan frontend mengakses API dari domain berbeda
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Di production, ganti dengan domain frontend spesifik
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/", summary="Health check")
def root():
    """Endpoint cek status API."""
    return {"status": "ok", "service": "Monitoring Arus Listrik Mesin Pabrik"}


@app.get("/status", summary="Status koneksi MQTT & Database")
def get_status():
    """Cek status koneksi MQTT broker dan database."""
    return {
        "mqtt_broker": MQTT_BROKER,
        "mqtt_topic": MQTT_TOPIC,
        "database": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "service": "running"
    }


@app.get("/logs", summary="Ambil log pembacaan arus terbaru")
def get_logs(
    limit: int = Query(default=50, ge=1, le=500, description="Jumlah data yang ditampilkan"),
    nama_mesin: Optional[str] = Query(default=None, description="Filter berdasarkan nama mesin"),
    status: Optional[str] = Query(default=None, description="Filter: NORMAL, WARNING, CRITICAL")
):
    """
    Ambil data log arus dari database.
    - **limit**: Maksimal baris yang dikembalikan (default 50)
    - **nama_mesin**: Filter per mesin (opsional)
    - **status**: Filter per status (opsional)
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        # Bangun query dinamis berdasarkan filter yang diberikan
        query = """
            SELECT id, nama_mesin, nilai_arus, status_mesin,
                   lokasi, keterangan, waktu_simpan
            FROM logs_mesin
            WHERE 1=1
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

        # Format hasil query menjadi list of dict
        columns = ["id", "nama_mesin", "nilai_arus", "status_mesin",
                   "lokasi", "keterangan", "waktu_simpan"]
        result = [dict(zip(columns, row)) for row in rows]

        return {"total": len(result), "data": result}

    except psycopg2.Error as e:
        logger.error(f"❌ Error query database: {e}")
        raise HTTPException(status_code=500, detail="Database error")

    finally:
        if conn:
            release_db_conn(conn)


@app.get("/statistik", summary="Statistik ringkasan per mesin")
def get_statistik():
    """
    Ambil statistik ringkasan: rata-rata arus, puncak arus, dan
    jumlah alert per mesin dalam 24 jam terakhir.
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        query = """
            SELECT
                nama_mesin,
                COUNT(*)                        AS total_pembacaan,
                ROUND(AVG(nilai_arus)::NUMERIC, 2) AS rata_rata_arus,
                ROUND(MAX(nilai_arus)::NUMERIC, 2) AS puncak_arus,
                COUNT(*) FILTER (WHERE status_mesin = 'WARNING')  AS total_warning,
                COUNT(*) FILTER (WHERE status_mesin = 'CRITICAL') AS total_critical,
                MAX(waktu_simpan)               AS terakhir_update
            FROM logs_mesin
            WHERE waktu_simpan >= NOW() - INTERVAL '24 hours'
            GROUP BY nama_mesin
            ORDER BY nama_mesin
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        columns = ["nama_mesin", "total_pembacaan", "rata_rata_arus",
                   "puncak_arus", "total_warning", "total_critical", "terakhir_update"]
        result = [dict(zip(columns, row)) for row in rows]

        return {"periode": "24 jam terakhir", "data": result}

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Database error")

    finally:
        if conn:
            release_db_conn(conn)


@app.get("/mesin", summary="Daftar semua mesin yang terdaftar")
def get_daftar_mesin():
    """Ambil daftar mesin dari tabel daftar_mesin."""
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT nama_mesin, tipe_mesin, lokasi, batas_arus_max,
                   batas_arus_warning, aktif
            FROM daftar_mesin
            ORDER BY nama_mesin
        """)
        rows = cursor.fetchall()

        columns = ["nama_mesin", "tipe_mesin", "lokasi", "batas_arus_max",
                   "batas_arus_warning", "aktif"]
        result = [dict(zip(columns, row)) for row in rows]

        return {"total": len(result), "data": result}

    except psycopg2.Error as e:
        raise HTTPException(status_code=500, detail="Database error")

    finally:
        if conn:
            release_db_conn(conn)

@app.get("/mesin/status", summary="Status terkini semua mesin aktif")
def get_status_mesin():
    """
    Gabungkan daftar_mesin dengan log terbaru dan statistik 24 jam.
    Mesin yang belum pernah kirim data tetap muncul dengan nilai null.
    """
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                dm.nama_mesin,
                dm.tipe_mesin,
                dm.lokasi,
                dm.batas_arus_max,
                dm.batas_arus_warning,

                -- Log terbaru (bisa NULL kalau belum ada data)
                latest.nilai_arus       AS nilai_arus_terkini,
                latest.status_mesin     AS status_terkini,
                latest.waktu_simpan     AS waktu_terkini,

                -- Statistik 24 jam (bisa NULL kalau belum ada data)
                stat.total_pembacaan,
                stat.rata_rata_arus,
                stat.puncak_arus,
                stat.total_warning,
                stat.total_critical

            FROM daftar_mesin dm

            -- JOIN log terbaru per mesin
            LEFT JOIN LATERAL (
                SELECT nilai_arus, status_mesin, waktu_simpan
                FROM logs_mesin
                WHERE nama_mesin = dm.nama_mesin
                ORDER BY waktu_simpan DESC
                LIMIT 1
            ) latest ON TRUE

            -- JOIN statistik 24 jam
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
            "nama_mesin", "tipe_mesin", "lokasi", "batas_arus_max", "batas_arus_warning",
            "nilai_arus_terkini", "status_terkini", "waktu_terkini",
            "total_pembacaan", "rata_rata_arus", "puncak_arus",
            "total_warning", "total_critical"
        ]
        result = [dict(zip(columns, row)) for row in rows]

        # Serialisasi datetime agar JSON-able
        for r in result:
            if r["waktu_terkini"]:
                r["waktu_terkini"] = r["waktu_terkini"].isoformat()

        return {"total": len(result), "data": result}

    except psycopg2.Error as e:
        logger.error(f"❌ Error query status mesin: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn:
            release_db_conn(conn)
            
class MesinCreate(BaseModel):
    nama_mesin: str
    tipe_mesin: Optional[str] = None
    lokasi: Optional[str] = None
    batas_arus_max: float = 20.0
    batas_arus_warning: float = 15.0
    aktif: bool = True

class MesinUpdate(BaseModel):
    tipe_mesin: Optional[str] = None
    lokasi: Optional[str] = None
    batas_arus_max: Optional[float] = None
    batas_arus_warning: Optional[float] = None
    aktif: Optional[bool] = None


@app.post("/mesin", summary="Tambah mesin baru")
def tambah_mesin(body: MesinCreate):
    conn = None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO daftar_mesin
                (nama_mesin, tipe_mesin, lokasi, batas_arus_max, batas_arus_warning, aktif)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (body.nama_mesin, body.tipe_mesin, body.lokasi,
              body.batas_arus_max, body.batas_arus_warning, body.aktif))
        new_id = cursor.fetchone()[0]
        conn.commit()
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
        if body.tipe_mesin is not None:
            fields.append("tipe_mesin = %s"); values.append(body.tipe_mesin)
        if body.lokasi is not None:
            fields.append("lokasi = %s"); values.append(body.lokasi)
        if body.batas_arus_max is not None:
            fields.append("batas_arus_max = %s"); values.append(body.batas_arus_max)
        if body.batas_arus_warning is not None:
            fields.append("batas_arus_warning = %s"); values.append(body.batas_arus_warning)
        if body.aktif is not None:
            fields.append("aktif = %s"); values.append(body.aktif)

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
        return {"success": True, "deleted": nama_mesin}
    except HTTPException:
        raise
    except psycopg2.Error as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        if conn: release_db_conn(conn)

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

    # Jalankan FastAPI server dengan uvicorn
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,   # Set True hanya untuk development
        log_level="info"
    )