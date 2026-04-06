"""
============================================================
 FILE    : backend/main.py
 FUNGSI  : Entry point — wiring semua layer bersama
           MQTT consumer + FastAPI + DB pool
============================================================
"""

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from repositories import db
from mqtt import consumer
from api.routes import devices, tags, logs, mqtt as mqtt_routes

# ── LOGGING ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── ENV ──────────────────────────────────────────────────────
load_dotenv()

DB_HOST        = os.getenv("DB_HOST", "localhost")
DB_PORT        = int(os.getenv("DB_PORT", "5432"))
DB_NAME        = os.getenv("DB_NAME", "monitoring_pabrik")
DB_USER        = os.getenv("DB_USER", "postgres")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "password")

MQTT_BROKER    = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "efortech-monitor-001")

API_HOST       = os.getenv("API_HOST", "0.0.0.0")
API_PORT       = int(os.getenv("API_PORT", "8000"))


# ── LIFESPAN ─────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup  : init DB pool → connect MQTT
    Shutdown : disconnect MQTT → close DB pool
    """
    logger.info("=" * 60)
    logger.info("  INDUSTRIAL IoT MONITOR v2.0 — Topic-based Architecture")
    logger.info("=" * 60)
    logger.info(f"  MQTT Broker : {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"  Database    : {DB_HOST}:{DB_PORT}/{DB_NAME}")
    logger.info(f"  API         : http://{API_HOST}:{API_PORT}")
    logger.info(f"  API Docs    : http://localhost:{API_PORT}/docs")
    logger.info("=" * 60)

    # 1. Init database connection pool
    db.init_pool(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
    )

    # 2. Connect MQTT — subscription_manager akan sync dari DB
    app.state.mqtt_client = consumer.create_client(
        broker_host=MQTT_BROKER,
        broker_port=MQTT_PORT,
        client_id=MQTT_CLIENT_ID,
    )

    yield  # ← aplikasi berjalan

    # 3. Shutdown
    logger.info("🛑 Menghentikan aplikasi...")
    app.state.mqtt_client.loop_stop()
    app.state.mqtt_client.disconnect()
    db.close_pool()


# ── FASTAPI APP ───────────────────────────────────────────────
app = FastAPI(
    title="Industrial IoT Monitor API",
    description=(
        "REST API untuk sistem monitoring IoT berbasis topic MQTT.\n\n"
        "**Format topic:** `pabrik/{factory_id}/{device_id}/{tag_name}`\n\n"
        "**Format payload:** `{\"value\": 12.5, \"timestamp\": \"...\"}`"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ── REGISTER ROUTES ───────────────────────────────────────────
app.include_router(devices.router)
app.include_router(tags.router)
app.include_router(logs.router)
app.include_router(mqtt_routes.router)


# ── HEALTH ENDPOINTS ──────────────────────────────────────────
@app.get("/", tags=["health"], summary="Health check")
def health():
    return {
        "status":       "ok",
        "version":      "2.0.0",
        "architecture": "topic-based",
        "docs":         f"http://localhost:{API_PORT}/docs",
    }


@app.get("/status", tags=["health"], summary="Status koneksi & ringkasan sistem")
def system_status():
    from services import subscription_manager
    return {
        "mqtt": {
            "broker":            f"{MQTT_BROKER}:{MQTT_PORT}",
            "client_id":         MQTT_CLIENT_ID,
            "subscribed_topics": sorted(subscription_manager.get_subscribed()),
            "total_topics":      len(subscription_manager.get_subscribed()),
        },
        "database": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "service":  "running",
    }


# ── ENTRY POINT ───────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
    )