#!/usr/bin/env python3
"""
bridge.py — Puente MQTT <-> PostgreSQL & MongoDB (NoSQL)
Equivalente Python del bridge Rust extendido.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt_client
import psycopg2
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuración MQTT y Entorno
# ---------------------------------------------------------------------------

MQTT_HOST      = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = f"{os.getenv('MQTT_CLIENT_ID', 'mqtt-db-bridge-py')}-{int(time.time() * 1000) % 10000}"

# Topics SQL
TOPIC_DB_PUSH   = "giirob/pr2-A1/db/push"
TOPIC_DB_PULL   = "giirob/pr2-A1/db/pull"
TOPIC_PULL_RESP = "giirob/pr2-A1/db/pull/response"

# Topic NoSQL
TOPIC_NOSQL_PUSH = "giirob/pr2-A1/nosql/push"

# Colecciones permitidas en MongoDB
ALLOWED_NOSQL_COLLECTIONS = {
    "alertas_tolva", 
    "ciclos_cobot", 
    "comandos_scada", 
    "despachos_amr", 
    "emergencias", 
    "eventos_cinta"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Conexiones a Bases de Datos (SQL y NoSQL)
# --------------------------------------------------------------------------

def connect_pg_db() -> psycopg2.extensions.connection:
    """Conexión a PostgreSQL"""
    target_dbname = os.getenv("PGDATABASE", "db-pr2")
    DATABASE_URL = os.getenv("DATABASE_URL")

    if DATABASE_URL:
        conn = psycopg2.connect(psycopg2.extensions.make_dsn(DATABASE_URL, dbname=target_dbname))
    else:
        conn = psycopg2.connect(
            dbname=target_dbname,
            user=os.getenv("PGUSER", os.getenv("USER")),
            password=os.getenv("PGPASSWORD"),
            host=os.getenv("PGHOST", "localhost"),
            port=os.getenv("PGPORT", "5432"),
        )

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET search_path TO pr2_a1_db, public")

    conn.autocommit = False
    log.info("PostgreSQL conectado")
    return conn

def connect_mongo_db():
    """Conexión a MongoDB"""
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    mongo_db_name = os.getenv("MONGO_DB_NAME", "pr2_nosql_db")
    
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')  # Fuerza una llamada para verificar la conexión
        log.info("MongoDB (NoSQL) conectado")
        return client[mongo_db_name]
    except Exception as e:
        log.error("Error conectando a MongoDB. Los eventos NoSQL fallarán: %s", e)
        return None

def safe_execute(conn, func, *args):
    """Ejecuta func(conn, *args) dentro de una transacción PG con rollback automático."""
    try:
        func(conn, *args)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error("Error en transacción PostgreSQL — rollback: %s", exc)


# ---------------------------------------------------------------------------
# Handlers NoSQL (MongoDB)
# ---------------------------------------------------------------------------

def handle_nosql_push(mongo_db, payload: str) -> None:
    if mongo_db is None:
        log.warning("Se omitió evento NoSQL (MongoDB no conectado).")
        return

    try:
        val = json.loads(payload)
    except json.JSONDecodeError:
        log.error("JSON inválido en nosql/push: %s", payload)
        return

    # Esperamos que el JSON tenga un campo "coleccion" indicando el destino
    coleccion_destino = val.get("coleccion", "").lower().strip()

    if coleccion_destino not in ALLOWED_NOSQL_COLLECTIONS:
        log.warning("Intento de inserción en colección NoSQL no permitida o no definida: '%s'", coleccion_destino)
        return

    # Extraemos los datos a insertar. 
    # Si viene envuelto en un campo "data", lo usamos. Si no, metemos todo el JSON.
    documento = val.get("data", val.copy())
    
    # Limpiamos el campo de enrutamiento si guardamos el objeto completo
    if "coleccion" in documento:
        del documento["coleccion"]

    # Añadimos un timestamp automático de recepción (buena práctica en IoT/NoSQL)
    documento["_ts_recepcion"] = datetime.now(timezone.utc).isoformat()

    try:
        resultado = mongo_db[coleccion_destino].insert_one(documento)
        log.info("Mongo [%s]: Inserción OK (id: %s)", coleccion_destino, resultado.inserted_id)
    except Exception as e:
        log.error("Error insertando documento en MongoDB [%s]: %s", coleccion_destino, e)


# ---------------------------------------------------------------------------
# Handlers SQL (PostgreSQL) db/push
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
    id_color    = val.get("id_color", "").lower().strip()
    estado      = bool(val.get("estado", False))
    id_operario = val.get("id_operario")

    if not id_caja or not id_palet or not id_color:
        log.warning("caja_paletizada con campos faltantes: %s", val)
        return

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO palet (id_palet, id_color, estado)
               VALUES (%s, %s, %s)
               ON CONFLICT (id_palet) DO UPDATE SET estado = EXCLUDED.estado""",
            (id_palet, id_color, estado),
        )
        cur.execute(
            "UPDATE caja SET id_palet = %s WHERE id_caja = %s",
            (id_palet, id_caja),
        )
        if estado and id_operario:
            cur.execute(
                "UPDATE palet SET id_operario = %s WHERE id_palet = %s",
                (str(id_operario).strip(), id_palet),
            )
        log.info("SQL: Paletizado caja=%s palet=%s", id_caja, id_palet)

def _handle_box_completed(conn, val: dict) -> None:
    id_caja         = val.get("id_caja", "").strip()
    color           = val.get("color", "").lower().strip()
    codigo_etiqueta = val.get("codigo_etiqueta", "").strip()
    estado          = bool(val.get("estado", False))
    lotes           = val.get("lotes", [])

    if not id_caja or not color:
        log.warning("box_completed con campos faltantes: %s", val)
        return

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO caja (id_caja, color, codigo_etiqueta, estado)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id_caja) DO UPDATE
               SET color = EXCLUDED.color,
                   codigo_etiqueta = EXCLUDED.codigo_etiqueta,
                   estado = EXCLUDED.estado""",
            (id_caja, color, codigo_etiqueta, estado),
        )
        for lote_id in lotes:
            lote_id = str(lote_id).strip()
            if not lote_id: continue
            cur.execute("SELECT 1 FROM lote WHERE id_lote = %s", (lote_id,))
            if cur.fetchone() is None: continue
            cur.execute(
                """INSERT INTO material_caja (lote, id_caja)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (lote_id, id_caja),
            )
        log.info("SQL: Box completed caja=%s", id_caja)

def _handle_tapa_clasificada(conn, val: dict) -> None:
    id_lote  = val.get("id_lote", "").strip()
    cantidad = int(val.get("cantidad", 1))

    if not id_lote: return

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE lote SET total_tapas_clasificadas = total_tapas_clasificadas + %s
               WHERE id_lote = %s AND total_tapas_clasificadas + %s <= total_tapas_entrada""",
            (cantidad, id_lote, cantidad),
        )
        log.info("SQL: Tapa clasificada lote=%s cant=%d", id_lote, cantidad)

def _handle_reset(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE lote SET total_tapas_clasificadas = 0")
        log.info("SQL: Lotes reiniciados")


# ---------------------------------------------------------------------------
# Handlers SQL (PostgreSQL) db/pull
# ---------------------------------------------------------------------------

def handle_db_pull(conn: psycopg2.extensions.connection, client, payload: str) -> None:
    try:
        val = json.loads(payload)
    except json.JSONDecodeError:
        return

    query = val.get("query", "").lower()
    if query == "operarios": _query_operarios(conn, client)
    elif query == "lote_pendiente": _query_lote_pendiente(conn, client)

def _query_operarios(conn, client) -> None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_operario, nombre, apellido FROM operario")
        rows = cur.fetchall()
    
    lista = [{"id_operario": r["id_operario"].strip(), "nombre": r["nombre"].strip(), "apellido": r["apellido"].strip()} for r in rows]
    client.publish(TOPIC_PULL_RESP, json.dumps({"operarios": lista}), qos=1)

def _query_lote_pendiente(conn, client) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id_lote, total_tapas_entrada - total_tapas_clasificadas AS pendientes
               FROM lote WHERE total_tapas_clasificadas < total_tapas_entrada
               ORDER BY fecha_inicio ASC LIMIT 1"""
        )
        row = cur.fetchone()

    if row:
        lote_id, pendientes = row
        client.publish(TOPIC_PULL_RESP, json.dumps({"lote_id": lote_id.strip(), "quantity": pendientes, "color": "red"}), qos=1)
    else:
        client.publish(TOPIC_PULL_RESP, json.dumps({"lote_id": None}), qos=1)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    pg_conn = connect_pg_db()
    mongo_db = connect_mongo_db()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT conectado al broker")
            client.subscribe(TOPIC_DB_PUSH, qos=1)
            client.subscribe(TOPIC_DB_PULL, qos=1)
            client.subscribe(TOPIC_NOSQL_PUSH, qos=1) # Nuevo topic NoSQL
            log.info("Suscrito a SQL Push/Pull y NoSQL Push")
        else:
            log.error("Error al conectar a MQTT, código: %d", rc)

    def on_message(client, userdata, msg):
        topic   = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        log.info("Mensaje en [%s]: %s", topic, payload)

        if topic == TOPIC_DB_PUSH:
            handle_db_push(pg_conn, payload)
        elif topic == TOPIC_DB_PULL:
            handle_db_pull(pg_conn, client, payload)
        elif topic == TOPIC_NOSQL_PUSH:
            handle_nosql_push(mongo_db, payload) # Enrutador hacia MongoDB

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