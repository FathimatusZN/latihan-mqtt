"""
============================================================
 FILE    : backend/mqtt/consumer.py
 FUNGSI  : MQTT consumer layer — satu-satunya tempat yang
           bersentuhan langsung dengan broker dan paho-mqtt.

           Tanggung jawab:
             1. Setup & connect ke broker
             2. on_connect: sync subscriptions
             3. on_message: parse topic + payload → ParsedMqttMessage
             4. Delegasi ke ingestion service

           TIDAK ada logika bisnis di sini.
           TIDAK ada SQL di sini.
============================================================
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt

from models.schemas import ParsedMqttMessage
from services import ingestion, subscription_manager

logger = logging.getLogger(__name__)


# ── TOPIC PARSER ─────────────────────────────────────────────

def parse_topic(topic: str) -> Optional[tuple[str, str, str]]:
    """
    Parse MQTT topic dengan format:
        pabrik/{factory_id}/{device_id}/{tag_name}

    Return: (factory_id, device_id, tag_name)
            atau None jika format tidak sesuai.

    Contoh:
        "pabrik/efortech/PM_001/current"
        → ("efortech", "PM_001", "current")
    """
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "pabrik":
        return None
    _, factory_id, device_id, tag_name = parts
    if not all([factory_id, device_id, tag_name]):
        return None
    return factory_id, device_id, tag_name


def parse_payload(raw: bytes) -> Optional[tuple[float, Optional[datetime]]]:
    """
    Parse payload MQTT. Format yang diterima:
      Format utama (minimal):
        {"value": 10.9}

      Format lengkap (dari gateway):
        {"value": 10.9, "timestamp": "2026-04-02T10:00:00Z"}

      Format flat (kompatibilitas gateway lama / Node-RED):
        10.9   ← plain number string

    Return: (value, ts_sensor) atau None jika tidak valid.
    """
    decoded = raw.decode("utf-8", errors="replace").strip()

    # Plain number (misal dari gateway atau script sederhana)
    try:
        value = float(decoded)
        return value, None
    except ValueError:
        pass

    # JSON payload
    try:
        obj = json.loads(decoded)
    except json.JSONDecodeError:
        logger.warning(f"⚠️  Payload bukan JSON valid: {decoded[:80]!r}")
        return None

    # Ekstrak value — fleksibel terhadap key
    value_raw = obj.get("value") or obj.get("v") or obj.get("val")
    if value_raw is None:
        logger.warning(f"⚠️  Field 'value' tidak ditemukan di payload: {obj}")
        return None

    try:
        value = float(value_raw)
    except (ValueError, TypeError):
        logger.warning(f"⚠️  'value' tidak bisa dikonversi ke float: {value_raw!r}")
        return None

    # Timestamp opsional
    ts_sensor: Optional[datetime] = None
    ts_raw = obj.get("timestamp") or obj.get("ts") or obj.get("time")
    if ts_raw:
        try:
            ts_sensor = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        except ValueError:
            logger.debug(f"Timestamp tidak valid, diabaikan: {ts_raw!r}")

    return value, ts_sensor


# ── MQTT CALLBACKS ────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        broker_host = userdata.get("broker_host", "?")
        broker_port = userdata.get("broker_port", "?")
        logger.info(f"✅ Terhubung ke broker {broker_host}:{broker_port}")
        subscription_manager.sync()
    else:
        _RC_MESSAGES = {
            1: "versi protokol tidak didukung",
            2: "client ID tidak valid",
            3: "broker tidak tersedia",
            4: "username/password salah",
            5: "tidak diizinkan",
        }
        reason = _RC_MESSAGES.get(rc, f"rc={rc}")
        logger.error(f"❌ Koneksi ditolak broker: {reason}")


def on_disconnect(client, userdata, rc):
    if rc != 0:
        logger.warning(f"⚠️  Koneksi terputus (rc={rc}), menunggu reconnect otomatis...")


def on_message(client, userdata, msg):
    """
    Entry point setiap pesan MQTT masuk.

    Alur:
      1. Parse topic → (factory_id, device_id, tag_name)
      2. Parse payload → (value, ts_sensor)
      3. Buat ParsedMqttMessage
      4. Delegasi ke ingestion.process_message()
    """
    topic   = msg.topic
    payload = msg.payload

    logger.debug(f"📨 Pesan masuk | topic={topic}")

    # 1. Parse topic
    parsed_topic = parse_topic(topic)
    if parsed_topic is None:
        logger.warning(
            f"⚠️  Format topic tidak dikenali: {topic!r} "
            f"(expected: pabrik/{{factory_id}}/{{device_id}}/{{tag_name}})"
        )
        return

    factory_id, device_id, tag_name = parsed_topic

    # 2. Parse payload
    parsed_payload = parse_payload(payload)
    if parsed_payload is None:
        logger.warning(f"⚠️  Payload tidak valid | topic={topic}")
        return

    value, ts_sensor = parsed_payload

    # 3. Buat domain object
    message = ParsedMqttMessage(
        factory_id=factory_id,
        device_id=device_id,
        tag_name=tag_name,
        raw_topic=topic,
        value=value,
        ts_sensor=ts_sensor,
    )

    # 4. Proses (simpan ke DB)
    ingestion.process_message(message)


# ── SETUP CLIENT ──────────────────────────────────────────────

def create_client(
    broker_host: str,
    broker_port: int,
    client_id:   str,
) -> mqtt.Client:
    """
    Buat dan connect MQTT client.
    Loop dijalankan di background thread (loop_start).
    """
    userdata = {"broker_host": broker_host, "broker_port": broker_port}

    client = mqtt.Client(client_id=client_id, userdata=userdata)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    # Reconnect otomatis dengan exponential backoff
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    logger.info(f"🔌 Menghubungkan ke broker {broker_host}:{broker_port}...")
    client.connect(broker_host, broker_port, keepalive=60)
    client.loop_start()

    # Daftarkan ke subscription_manager agar bisa sync
    subscription_manager.set_client(client)

    return client