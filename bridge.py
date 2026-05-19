#!/usr/bin/env python3
"""
bridge.py — Puente MQTT <-> PostgreSQL
Equivalente Python del bridge Rust en c:/p/d/bridge/src/main.rs
"""

import json
import logging
import os
import time

import paho.mqtt.client as mqtt_client
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

MQTT_HOST      = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = f"{os.getenv('MQTT_CLIENT_ID', 'mqtt-db-bridge-py')}-{int(time.time() * 1000) % 10000}"
DATABASE_URL   = os.getenv("DATABASE_URL")

TOPIC_DB_PUSH   = "giirob/pr2-A1/db/push"
TOPIC_DB_PULL   = "giirob/pr2-A1/db/pull"
TOPIC_PULL_RESP = "giirob/pr2-A1/db/pull/response"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def connect_db() -> psycopg2.extensions.connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no definida en .env")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    log.info("PostgreSQL conectado")
    return conn


def safe_execute(conn, func, *args):
    """Ejecuta func(conn, *args) dentro de una transacción con rollback automático."""
    try:
        func(conn, *args)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error("Error en transacción — rollback: %s", exc)

# ---------------------------------------------------------------------------
# Handlers db/push
# ---------------------------------------------------------------------------

def handle_db_push(conn: psycopg2.extensions.connection, payload: str) -> None:
    try:
        val = json.loads(payload)
    except json.JSONDecodeError:
        log.error("JSON inválido en db/push: %s", payload)
        return

    event = val.get("event", "").lower()

    if event == "caja_paletizada":
        safe_execute(conn, _handle_caja_paletizada, val)
    elif event == "box_completed":
        safe_execute(conn, _handle_box_completed, val)
    elif event == "tapa_clasificada":
        safe_execute(conn, _handle_tapa_clasificada, val)
    elif event == "reset":
        safe_execute(conn, _handle_reset)
    else:
        log.warning("Evento desconocido en db/push: %s", event)


def _handle_caja_paletizada(conn, val: dict) -> None:
    id_caja     = val.get("id_caja", "").strip()
    id_palet    = val.get("id_palet", "").strip()
    id_color    = val.get("id_color", "").upper().strip()
    estado      = bool(val.get("estado", False))
    id_operario = val.get("id_operario")

    if not id_caja or not id_palet or not id_color:
        log.warning("caja_paletizada con campos faltantes: %s", val)
        return

    log.info("Paletizando: caja=%s palet=%s color=%s estado=%s", id_caja, id_palet, id_color, estado)

    with conn.cursor() as cur:
        # 1. Upsert palet
        cur.execute(
            """INSERT INTO palet (id_palet, id_color, estado)
               VALUES (%s, %s, %s)
               ON CONFLICT (id_palet) DO UPDATE SET estado = EXCLUDED.estado""",
            (id_palet, id_color, estado),
        )
        log.info("Palet %s upserted", id_palet)

        # 2. Vincular caja al palet
        cur.execute(
            "UPDATE caja SET id_palet = %s WHERE id_caja = %s",
            (id_palet, id_caja),
        )
        log.info("Caja %s vinculada a palet %s (%d fila/s)", id_caja, id_palet, cur.rowcount)

        # 3. Asignar operario de cierre si el palet queda cerrado
        if estado:
            if id_operario:
                cur.execute(
                    "UPDATE palet SET id_operario = %s WHERE id_palet = %s",
                    (str(id_operario).strip(), id_palet),
                )
                log.info("Operario %s asignado como cierre del palet %s", id_operario, id_palet)
            else:
                log.warning("Palet %s cerrado sin id_operario", id_palet)


def _handle_box_completed(conn, val: dict) -> None:
    id_caja         = val.get("id_caja", "").strip()
    color           = val.get("color", "").upper().strip()
    codigo_etiqueta = val.get("codigo_etiqueta", "").strip()
    estado          = bool(val.get("estado", False))
    lotes           = val.get("lotes", [])

    if not id_caja or not color:
        log.warning("box_completed con campos faltantes: %s", val)
        return

    log.info("Box completed: caja=%s color=%s etiqueta=%s lotes=%s", id_caja, color, codigo_etiqueta, lotes)

    with conn.cursor() as cur:
        # Insertar caja (sin palet aún, se asigna en caja_paletizada)
        cur.execute(
            """INSERT INTO caja (id_caja, color, codigo_etiqueta, estado)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id_caja) DO UPDATE
               SET color = EXCLUDED.color,
                   codigo_etiqueta = EXCLUDED.codigo_etiqueta,
                   estado = EXCLUDED.estado""",
            (id_caja, color, codigo_etiqueta, estado),
        )
        log.info("Caja %s insertada/actualizada", id_caja)

        # Vincular caja a cada lote en material_caja
        for lote_id in lotes:
            cur.execute(
                """INSERT INTO material_caja (lote, id_caja)
                   VALUES (%s, %s)
                   ON CONFLICT DO NOTHING""",
                (str(lote_id).strip(), id_caja),
            )
            log.info("Caja %s vinculada a lote %s", id_caja, lote_id)


def _handle_tapa_clasificada(conn, val: dict) -> None:
    id_lote  = val.get("id_lote", "").strip()
    cantidad = int(val.get("cantidad", 1))

    if not id_lote:
        log.warning("tapa_clasificada sin id_lote: %s", val)
        return

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE lote
               SET total_tapas_clasificadas = total_tapas_clasificadas + %s
               WHERE id_lote = %s
                 AND total_tapas_clasificadas + %s <= total_tapas_entrada""",
            (cantidad, id_lote, cantidad),
        )
        if cur.rowcount > 0:
            log.info("%d tapa(s) clasificada(s) en lote %s", cantidad, id_lote)
        else:
            log.warning("Lote %s no encontrado o ya completo", id_lote)


def _handle_reset(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE lote SET total_tapas_clasificadas = 0")
        log.info("Reset: %d lote(s) reiniciado(s)", cur.rowcount)

# ---------------------------------------------------------------------------
# Handlers db/pull
# ---------------------------------------------------------------------------

def handle_db_pull(conn: psycopg2.extensions.connection, client, payload: str) -> None:
    try:
        val = json.loads(payload)
    except json.JSONDecodeError:
        log.error("JSON inválido en db/pull: %s", payload)
        return

    query = val.get("query", "").lower()

    if query == "operarios":
        _query_operarios(conn, client)
    elif query == "lote_pendiente":
        _query_lote_pendiente(conn, client)
    else:
        log.warning("db/pull query desconocida: %s", query)


def _query_operarios(conn, client) -> None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_operario, nombre, apellido FROM operario")
        rows = cur.fetchall()

    lista = [
        {
            "id_operario": r["id_operario"].strip(),
            "nombre":      r["nombre"].strip(),
            "apellido":    r["apellido"].strip(),
        }
        for r in rows
    ]
    resp = json.dumps({"operarios": lista})
    client.publish(TOPIC_PULL_RESP, resp, qos=1)
    log.info("Operarios enviados: %d registros", len(lista))


def _query_lote_pendiente(conn, client) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id_lote, total_tapas_entrada - total_tapas_clasificadas AS pendientes
               FROM lote
               WHERE total_tapas_clasificadas < total_tapas_entrada
               ORDER BY fecha_inicio ASC
               LIMIT 1"""
        )
        row = cur.fetchone()

    if row:
        lote_id, pendientes = row
        resp = json.dumps({
            "lote_id":  lote_id.strip(),
            "quantity": pendientes,
            "color":    "red",
        })
        client.publish(TOPIC_PULL_RESP, resp, qos=1)
        log.info("Lote pendiente enviado: %s (%d tapas)", lote_id.strip(), pendientes)
    else:
        # Demo: reiniciar lotes cuando todos están completos
        with conn.cursor() as cur:
            cur.execute("UPDATE lote SET total_tapas_clasificadas = 0")
            conn.commit()
            log.info("Demo reset: %d lote(s) reiniciado(s)", cur.rowcount)
        resp = json.dumps({"lote_id": None})
        client.publish(TOPIC_PULL_RESP, resp, qos=1)
        log.warning("Todos los lotes completados — demo reiniciado automáticamente")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    conn = connect_db()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT conectado al broker")
            client.subscribe(TOPIC_DB_PUSH, qos=1)
            client.subscribe(TOPIC_DB_PULL, qos=1)
            log.info("Suscrito a %s y %s", TOPIC_DB_PUSH, TOPIC_DB_PULL)
        else:
            log.error("Error al conectar a MQTT, código: %d", rc)

    def on_message(client, userdata, msg):
        topic   = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        log.info("Mensaje en [%s]: %s", topic, payload)

        if topic == TOPIC_DB_PUSH:
            handle_db_push(conn, payload)
        elif topic == TOPIC_DB_PULL:
            handle_db_pull(conn, client, payload)

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            log.warning("Desconectado inesperadamente (rc=%d) — reconectando...", rc)

    client = mqtt_client.Client(client_id=MQTT_CLIENT_ID, protocol=mqtt_client.MQTTv311)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    log.info("Conectando a MQTT %s:%d con ID=%s", MQTT_HOST, MQTT_PORT, MQTT_CLIENT_ID)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)

    log.info("Bridge listo — esperando mensajes MQTT...")
    client.loop_forever()


if __name__ == "__main__":
    main()
