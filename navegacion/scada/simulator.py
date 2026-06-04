"""Simulador de la célula GIIROB completa — ESP32 mock + robots virtuales.

Lanza un único proceso que actúa como:
  * ESP32-S3 (cerebro): recibe órdenes del SCADA, coordina todos los robots.
  * Cámara virtual: responde a cada `spawn` con una detección.
  * Delta: ejecuta picks y publica la confirmación `done`.
  * AMR: navega entre tolvas y cobot_pick con latencia simulada.
  * Cobot: paletiza cajas y publica `completed`.

Reutiliza los topics y umbrales declarados en `config.py` del SCADA, así que
cualquier cambio allí (broker, claves, etc.) se propaga aquí automáticamente.

Uso:
    python simulator.py            # arranca con timings rápidos
    python simulator.py --slow     # timings parecidos al sistema real
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from config import (
    AMR_ARRIVAL_DELAY_SECS,
    AMR_TOLVA_THRESHOLD,
    MQTT_HOST,
    MQTT_PORT,
    PALLET_CAPACITY,
    PALLET_COUNT,
    TOLVA_COLOR,
    TOPIC_AMR_ACTION,
    TOPIC_AMR_STATUS,
    TOPIC_CAMERA_DATA,
    TOPIC_COBOT_ACTION,
    TOPIC_COBOT_STATUS,
    TOPIC_DB_PUSH,
    TOPIC_DELTA_ACTION,
    TOPIC_EMERGENCY_ACTION,
    TOPIC_EMERGENCY_STATUS,
    TOPIC_ROBODK_ACTION,
    TOPIC_SCADA_ACTION,
    TOPIC_SCADA_STATUS,
    VALID_COLORS,
)


# ---------------------------------------------------------------------------
# Timings de la simulación (configurables al arrancar)
# ---------------------------------------------------------------------------


class Timings:
    """Tiempos de cada actor. Modificables con --slow / --fast."""

    LOGIC_TICK_S = 0.3
    SPAWN_INTERVAL_S = 1.0
    CAMERA_LATENCY_S = 0.3
    DELTA_PICK_S = 0.6
    AMR_TRAVEL_S = 2.5
    AMR_WAIT_TOLVA_S = 3.0      # equivalente a AMR_ARRIVAL_DELAY_SECS pero acelerado
    COBOT_PALLETIZE_S = 1.5
    STATUS_PUBLISH_S = 1.5

    @classmethod
    def apply_preset(cls, preset: str) -> None:
        if preset == "slow":
            cls.SPAWN_INTERVAL_S = 2.5
            cls.CAMERA_LATENCY_S = 0.5
            cls.DELTA_PICK_S = 1.5
            cls.AMR_TRAVEL_S = 6.0
            cls.AMR_WAIT_TOLVA_S = float(AMR_ARRIVAL_DELAY_SECS)
            cls.COBOT_PALLETIZE_S = 4.0
            cls.STATUS_PUBLISH_S = 2.0
        elif preset == "fast":
            cls.SPAWN_INTERVAL_S = 0.4
            cls.CAMERA_LATENCY_S = 0.1
            cls.DELTA_PICK_S = 0.2
            cls.AMR_TRAVEL_S = 1.0
            cls.AMR_WAIT_TOLVA_S = 1.5
            cls.COBOT_PALLETIZE_S = 0.5
            cls.STATUS_PUBLISH_S = 1.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_PRINT_LOCK = threading.Lock()


def log(actor: str, message: str) -> None:
    with _PRINT_LOCK:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {actor:>7s} │ {message}", flush=True)


# ---------------------------------------------------------------------------
# Hub MQTT compartido
# ---------------------------------------------------------------------------


class MqttHub:
    """Cliente MQTT único; cada actor se suscribe con un callback por topic."""

    def __init__(self, host: str = MQTT_HOST, port: int = MQTT_PORT) -> None:
        self.host = host
        self.port = port
        client_id = f"giirob-sim-{uuid.uuid4().hex[:6]}"
        self.client = mqtt.Client(client_id=client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.handlers: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[dict], None]) -> None:
        self.handlers[topic].append(handler)

    def publish(self, topic: str, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":"))
        self.client.publish(topic, data, qos=1)

    def start(self) -> None:
        log("mqtt", f"conectando a {self.host}:{self.port}…")
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            log("mqtt", f"conexión rechazada rc={rc}")
            return
        for topic in self.handlers:
            client.subscribe(topic, qos=1)
        log("mqtt", f"conectado · {len(self.handlers)} topics suscritos")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        for handler in self.handlers.get(msg.topic, []):
            try:
                handler(payload)
            except Exception as exc:
                log("mqtt", f"handler error en {msg.topic}: {exc}")


# ---------------------------------------------------------------------------
# Actores periféricos (Cámara, Delta, AMR, Cobot)
# ---------------------------------------------------------------------------


class CameraSim:
    """Tras un spawn publica una detección con el mismo id_cap."""

    def __init__(self, hub: MqttHub) -> None:
        self.hub = hub
        hub.subscribe(TOPIC_ROBODK_ACTION, self._on_spawn)

    def _on_spawn(self, payload: dict) -> None:
        if payload.get("cmd") != "spawn":
            return
        id_cap = payload.get("id_cap")
        color = payload.get("color")
        if not id_cap or not color:
            return

        def emit() -> None:
            self.hub.publish(
                TOPIC_CAMERA_DATA,
                {
                    "x": round(random.uniform(0.5, 2.0), 2),
                    "y": round(random.uniform(0.5, 2.0), 2),
                    "color": color,
                    "precision": round(random.uniform(0.96, 0.99), 2),
                    "id_cap": id_cap,
                },
            )
            log("camera", f"detectada {id_cap} color={color}")

        threading.Timer(Timings.CAMERA_LATENCY_S, emit).start()


class DeltaSim:
    """Tras un pick simula el movimiento y publica `done` en scada/status."""

    def __init__(self, hub: MqttHub) -> None:
        self.hub = hub
        hub.subscribe(TOPIC_DELTA_ACTION, self._on_pick)
        self._emergency = False
        hub.subscribe(TOPIC_EMERGENCY_STATUS, self._on_emergency)

    def _on_emergency(self, payload: dict) -> None:
        self._emergency = payload.get("status") == "emergency_active"

    def _on_pick(self, payload: dict) -> None:
        if payload.get("cmd") != "pick" or self._emergency:
            return
        id_cap = payload.get("id_cap")
        tolva = payload.get("tolva")
        if not id_cap or not tolva:
            return
        log("delta", f"pick {id_cap} → {tolva}")

        def deposited() -> None:
            if self._emergency:
                return
            self.hub.publish(
                TOPIC_SCADA_STATUS,
                {"cmd": "done", "id_cap": id_cap, "tolva": tolva},
            )
            log("delta", f"depositada {id_cap} en {tolva}")

        threading.Timer(Timings.DELTA_PICK_S, deposited).start()


class AmrSim:
    """Recibe goto, espera y publica `arrived`."""

    def __init__(self, hub: MqttHub) -> None:
        self.hub = hub
        hub.subscribe(TOPIC_AMR_ACTION, self._on_goto)
        self._emergency = False
        hub.subscribe(TOPIC_EMERGENCY_STATUS, self._on_emergency)

    def _on_emergency(self, payload: dict) -> None:
        self._emergency = payload.get("status") == "emergency_active"

    def _on_goto(self, payload: dict) -> None:
        if payload.get("cmd") != "goto" or self._emergency:
            return
        location = payload.get("location")
        if not isinstance(location, str):
            return
        log("amr", f"navegando a {location}…")

        def arrived() -> None:
            if self._emergency:
                return
            self.hub.publish(
                TOPIC_AMR_STATUS,
                {"status": "arrived", "location": location, "caja_id": ""},
            )
            log("amr", f"llegado a {location}")

        threading.Timer(Timings.AMR_TRAVEL_S, arrived).start()


class CobotSim:
    """Recibe start, simula paletizado y publica `completed`."""

    def __init__(self, hub: MqttHub) -> None:
        self.hub = hub
        hub.subscribe(TOPIC_COBOT_ACTION, self._on_start)
        self._emergency = False
        hub.subscribe(TOPIC_EMERGENCY_STATUS, self._on_emergency)

    def _on_emergency(self, payload: dict) -> None:
        self._emergency = payload.get("status") == "emergency_active"

    def _on_start(self, payload: dict) -> None:
        if payload.get("cmd") != "start" or self._emergency:
            return
        pallet = payload.get("id_pallet") or payload.get("pallet_id")
        if not pallet:
            return
        log("cobot", f"paletizando en {pallet}…")

        def done() -> None:
            if self._emergency:
                return
            self.hub.publish(
                TOPIC_COBOT_STATUS,
                {"status": "completed", "id_pallet": pallet},
            )
            log("cobot", f"completado pallet {pallet}")

        threading.Timer(Timings.COBOT_PALLETIZE_S, done).start()


# ---------------------------------------------------------------------------
# Mock del ESP32-S3
# ---------------------------------------------------------------------------


# Mapa de colores a índice de tolva, idéntico al firmware.
_COLOR_TO_TOLVA_IDX = {
    "red": 0,
    "yellow": 1,
    "green": 2,
    "white": 3,
    "orange": 4,
    "blue": 5,
}

_TOLVA_NAMES = list(TOLVA_COLOR.keys())  # ["TOLVA_1", …, "TOLVA_6"]


class Esp32Sim:
    """Cerebro virtual: replica el comportamiento del firmware Rust."""

    def __init__(self, hub: MqttHub) -> None:
        self.hub = hub
        self.lock = threading.RLock()
        self.stop_event = threading.Event()

        # Modo y lote
        self.mode = "auto"
        self.id_lote: Optional[str] = None

        # Auto
        self.auto_target = 0
        self.auto_spawned = 0
        self.auto_validated = 0
        self.color_rotation = itertools.cycle(VALID_COLORS)

        # Manual
        self.manual_remaining = 0
        self.manual_color: Optional[str] = None
        self.manual_spawn_pending = False
        self.expected_color: Optional[str] = None

        # Tolvas y pallets
        self.tolva_counts = [0] * 6
        self.pending_tolva_counts = [0] * 6
        self.pending_tapas: dict[str, int] = {}      # id_cap → tolva idx
        self.pallet_counts = [0] * PALLET_COUNT
        self.cobot_next_pallet = 0
        self.cobot_in_progress = False
        self.cobot_ready = False
        self.total_processed = 0

        # AMR
        self.amr_pending_tolva: Optional[int] = None
        self.amr_arrived_tolva: Optional[int] = None
        self.amr_arrived_at: Optional[float] = None
        self.amr_id_caja: Optional[str] = None

        # Counters de IDs
        self.id_cap_counter = 1
        self.id_caja_counter = 1
        self.id_pallet_counter = 1

        # Emergencia
        self.emergency = False

        # Throttling de spawn: evita generar todas las tapas a la vez.
        self._next_spawn_allowed_at = 0.0

        # Suscripciones
        hub.subscribe(TOPIC_SCADA_ACTION, self.on_scada_action)
        hub.subscribe(TOPIC_SCADA_STATUS, self.on_scada_status)
        hub.subscribe(TOPIC_CAMERA_DATA, self.on_camera_data)
        hub.subscribe(TOPIC_AMR_STATUS, self.on_amr_status)
        hub.subscribe(TOPIC_COBOT_STATUS, self.on_cobot_status)
        hub.subscribe(TOPIC_EMERGENCY_ACTION, self.on_emergency_action)

        # Hilos auxiliares
        threading.Thread(target=self._logic_loop, daemon=True).start()
        threading.Thread(target=self._status_loop, daemon=True).start()

    # ---------- Handlers de mensajes ----------

    def on_scada_action(self, payload: dict) -> None:
        if self.emergency:
            log("esp32", f"ignorado (emergencia): {payload}")
            return
        cmd = (payload.get("cmd") or "").lower()
        if cmd == "gen":
            self._cmd_gen(payload)
        elif cmd == "set_mode":
            self._cmd_set_mode(payload)
        elif cmd == "status":
            self.publish_status()
        elif cmd == "reset":
            self._cmd_reset()
        else:
            log("esp32", f"comando SCADA desconocido: {cmd!r}")

    def on_scada_status(self, payload: dict) -> None:
        # El Delta (o el SCADA virtual) confirma una entrega.
        if payload.get("cmd") != "done":
            return
        id_cap = payload.get("id_cap")
        tolva = payload.get("tolva")
        if not isinstance(id_cap, str) or not isinstance(tolva, str):
            return
        with self.lock:
            idx = self.pending_tapas.pop(id_cap, None)
            if idx is None:
                log("esp32", f"done desconocido {id_cap} (no pendiente)")
                return
            try:
                tolva_idx = _TOLVA_NAMES.index(tolva.upper())
            except ValueError:
                tolva_idx = idx
            if tolva_idx != idx:
                log("esp32", f"warning: {id_cap} esperado {_TOLVA_NAMES[idx]} pero entregado en {tolva}")
            self.pending_tolva_counts[idx] = max(0, self.pending_tolva_counts[idx] - 1)
            self.tolva_counts[idx] += 1
            self.total_processed += 1
            log("esp32", f"confirmada {id_cap} en {_TOLVA_NAMES[idx]} · counts={self.tolva_counts}")

    def on_camera_data(self, payload: dict) -> None:
        if self.emergency:
            return
        precision = payload.get("precision", 0)
        if not isinstance(precision, (int, float)) or precision <= 0.95:
            return
        id_cap = payload.get("id_cap")
        color = payload.get("color")
        x = payload.get("x")
        y = payload.get("y")
        if not isinstance(id_cap, str) or not isinstance(color, str):
            return

        with self.lock:
            # Validación de color según modo
            if self.mode == "manual" and self.expected_color and color != self.expected_color:
                log("esp32", f"descartada {id_cap} color={color} (esperaba {self.expected_color})")
                return

            tolva_idx = _COLOR_TO_TOLVA_IDX.get(color)
            if tolva_idx is None:
                log("esp32", f"color desconocido {color}, descartada {id_cap}")
                return

            # Protección de rebalsamiento
            if self.tolva_counts[tolva_idx] + self.pending_tolva_counts[tolva_idx] >= AMR_TOLVA_THRESHOLD:
                log("esp32", f"tolva {_TOLVA_NAMES[tolva_idx]} llena, descartada {id_cap}")
                return

            self.pending_tolva_counts[tolva_idx] += 1
            self.pending_tapas[id_cap] = tolva_idx

            self.auto_validated += 1 if self.mode == "auto" else 0
            if self.mode == "manual":
                self.manual_remaining = max(0, self.manual_remaining - 1)

        log("esp32", f"pick {id_cap} → {_TOLVA_NAMES[tolva_idx]} (color={color})")
        self.hub.publish(
            TOPIC_DELTA_ACTION,
            {
                "cmd": "pick",
                "x": x,
                "y": y,
                "color": color,
                "tolva": _TOLVA_NAMES[tolva_idx],
                "id_cap": id_cap,
                "reason": f"{self.mode}: aceptando tapa color {color}",
            },
        )

    def on_amr_status(self, payload: dict) -> None:
        if payload.get("status") != "arrived":
            return
        location = (payload.get("location") or "").upper()
        with self.lock:
            if location.startswith("TOLVA_"):
                try:
                    idx = _TOLVA_NAMES.index(location)
                except ValueError:
                    return
                self.amr_arrived_tolva = idx
                self.amr_arrived_at = time.time()
                log("esp32", f"AMR llegó a {location}, esperando {Timings.AMR_WAIT_TOLVA_S}s")
            elif location == "COBOT_PICK" or location == "cobot_pick".upper():
                self.cobot_ready = True
                log("esp32", "AMR llegó a cobot_pick → cobot listo")

    def on_cobot_status(self, payload: dict) -> None:
        if (payload.get("status") or "").lower() != "completed":
            return
        pallet = payload.get("id_pallet") or payload.get("pallet_id")
        with self.lock:
            idx = self.cobot_next_pallet
            self.pallet_counts[idx] += 1
            count = self.pallet_counts[idx]
            self.cobot_in_progress = False

            # Persistir caja_paletizada en BD (evento informativo para el bridge)
            id_caja = self.amr_id_caja or f"B{self.id_caja_counter:04d}"
            estado_full = count >= PALLET_CAPACITY
            payload_db: dict = {
                "event": "caja_paletizada",
                "id_caja": id_caja,
                "id_palet": pallet,
                "id_color": "RED",
                "estado": estado_full,
            }
            if estado_full:
                payload_db["id_operario"] = "OP001"
            self.hub.publish(TOPIC_DB_PUSH, payload_db)

            log("esp32", f"pallet {pallet} count={count}/{PALLET_CAPACITY}")

            if estado_full:
                self.hub.publish(
                    TOPIC_SCADA_STATUS,
                    {"event": "pallet_full", "id_palet": pallet},
                )
                self.pallet_counts[idx] = 0
                self.cobot_next_pallet = (self.cobot_next_pallet + 1) % PALLET_COUNT
                self.id_pallet_counter += 1
                log("esp32", f"PALLET LLENO {pallet} · rotando al siguiente")

        self.publish_status()

    def on_emergency_action(self, payload: dict) -> None:
        cmd = (payload.get("cmd") or "").lower()
        source = payload.get("source") or "unknown"
        if cmd == "estop":
            self.emergency = True
            log("esp32", f"EMERGENCIA activada por {source}")
            self.hub.publish(
                TOPIC_EMERGENCY_STATUS,
                {"status": "emergency_active", "source": source},
            )
        elif cmd == "resume":
            self.emergency = False
            log("esp32", f"emergencia desactivada por {source}")
            self.hub.publish(
                TOPIC_EMERGENCY_STATUS,
                {"status": "emergency_inactive", "source": source},
            )
        self.publish_status()

    # ---------- Comandos del SCADA ----------

    def _cmd_gen(self, payload: dict) -> None:
        id_lote = payload.get("id_lote") or payload.get("lote")
        quantity = payload.get("quantity")
        color = payload.get("color")
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            log("esp32", f"gen ignorado: quantity inválido ({quantity!r})")
            return
        if quantity <= 0:
            return
        if not isinstance(id_lote, str) or not id_lote:
            log("esp32", "gen ignorado: falta id_lote")
            return

        with self.lock:
            self.id_lote = id_lote
            if self.mode == "auto":
                self.auto_target = quantity
                self.auto_spawned = 0
                self.auto_validated = 0
                self.color_rotation = itertools.cycle(VALID_COLORS)
                log("esp32", f"lote auto {id_lote} arrancado · target={quantity}")
            elif self.mode == "manual":
                self.manual_color = color or "red"
                self.manual_remaining = 1
                self.manual_spawn_pending = True
                self.expected_color = self.manual_color
                log("esp32", f"tapa manual color={self.manual_color} lote={id_lote}")
        self.publish_status()

    def _cmd_set_mode(self, payload: dict) -> None:
        mode = (payload.get("mode") or "").lower()
        if mode not in ("auto", "manual"):
            return
        with self.lock:
            self.mode = mode
            self.expected_color = None
            self.manual_spawn_pending = False
            log("esp32", f"modo → {mode}")
        self.publish_status()

    def _cmd_reset(self) -> None:
        with self.lock:
            self.auto_target = 0
            self.auto_spawned = 0
            self.auto_validated = 0
            self.manual_remaining = 0
            self.manual_color = None
            self.manual_spawn_pending = False
            self.expected_color = None
            self.tolva_counts = [0] * 6
            self.pending_tolva_counts = [0] * 6
            self.pending_tapas.clear()
            self.pallet_counts = [0] * PALLET_COUNT
            self.cobot_next_pallet = 0
            self.cobot_in_progress = False
            self.cobot_ready = False
            self.amr_pending_tolva = None
            self.amr_arrived_tolva = None
            self.amr_arrived_at = None
            self.amr_id_caja = None
            self.id_lote = None
            self.total_processed = 0
            log("esp32", "RESET · contadores a cero")
        self.publish_status()

    # ---------- Bucles internos ----------

    def _logic_loop(self) -> None:
        """Equivalente al logic-task del firmware: spawn, AMR timeout, cobot."""
        while not self.stop_event.is_set():
            time.sleep(Timings.LOGIC_TICK_S)
            if self.emergency:
                continue
            with self.lock:
                self._tick_spawn_locked()
                self._tick_amr_timeout_locked()
                self._tick_cobot_locked()
                self._tick_amr_dispatch_locked()
                self._tick_batch_complete_locked()

    def _tick_spawn_locked(self) -> None:
        now = time.time()
        if now < self._next_spawn_allowed_at:
            return
        if self.mode == "auto" and self.auto_spawned < self.auto_target:
            color = next(self.color_rotation)
            self._spawn_locked(color)
        elif self.mode == "manual" and self.manual_spawn_pending and self.manual_remaining > 0:
            self._spawn_locked(self.manual_color or "red")
            self.manual_spawn_pending = False

    def _spawn_locked(self, color: str) -> None:
        id_cap = f"C{self.id_cap_counter:04d}"
        self.id_cap_counter += 1
        if self.mode == "auto":
            self.auto_spawned += 1
        self._next_spawn_allowed_at = time.time() + Timings.SPAWN_INTERVAL_S
        log("esp32", f"spawn {id_cap} color={color}")
        self.hub.publish(
            TOPIC_ROBODK_ACTION,
            {"cmd": "spawn", "id_cap": id_cap, "color": color},
        )

    def _tick_amr_dispatch_locked(self) -> None:
        if self.amr_pending_tolva is not None or self.amr_arrived_tolva is not None:
            return
        for idx, count in enumerate(self.tolva_counts):
            if count >= AMR_TOLVA_THRESHOLD:
                self.amr_pending_tolva = idx
                self.amr_id_caja = f"B{self.id_caja_counter:04d}"
                self.id_caja_counter += 1
                location = _TOLVA_NAMES[idx]
                log("esp32", f"despacho AMR → {location} (caja {self.amr_id_caja})")
                self.hub.publish(
                    TOPIC_AMR_ACTION,
                    {"cmd": "goto", "location": location},
                )
                return

    def _tick_amr_timeout_locked(self) -> None:
        if self.amr_arrived_tolva is None or self.amr_arrived_at is None:
            return
        elapsed = time.time() - self.amr_arrived_at
        if elapsed < Timings.AMR_WAIT_TOLVA_S:
            return
        idx = self.amr_arrived_tolva
        tolva_name = _TOLVA_NAMES[idx]
        id_caja = self.amr_id_caja or f"B{self.id_caja_counter:04d}"
        color_name = TOLVA_COLOR[tolva_name].upper()

        log("esp32", f"box_completed {id_caja} desde {tolva_name} → cobot_pick")
        self.hub.publish(
            TOPIC_DB_PUSH,
            {
                "event": "box_completed",
                "id_caja": id_caja,
                "color": color_name,
                "codigo_etiqueta": f"ETQ{self.id_caja_counter:07d}",
                "estado": True,
                "lotes": [self.id_lote] if self.id_lote else [],
            },
        )
        self.hub.publish(
            TOPIC_AMR_ACTION,
            {"cmd": "goto", "location": "cobot_pick"},
        )
        self.tolva_counts[idx] = 0
        self.amr_arrived_tolva = None
        self.amr_arrived_at = None
        self.amr_pending_tolva = None

    def _tick_cobot_locked(self) -> None:
        if not self.cobot_ready or self.cobot_in_progress:
            return
        pallet_id = f"P{self.id_pallet_counter:04d}"
        idx = self.cobot_next_pallet
        boxes_stacked = self.pallet_counts[idx]
        self.cobot_in_progress = True
        self.cobot_ready = False
        log("esp32", f"start cobot {pallet_id} boxes_stacked={boxes_stacked}")
        self.hub.publish(
            TOPIC_COBOT_ACTION,
            {
                "cmd": "start",
                "id_pallet": pallet_id,
                "color": "red",
                "boxes_stacked": boxes_stacked,
            },
        )

    def _tick_batch_complete_locked(self) -> None:
        if (
            self.mode == "auto"
            and self.auto_target > 0
            and self.auto_validated >= self.auto_target
            and self.auto_spawned >= self.auto_target
        ):
            log("esp32", f"lote {self.id_lote} completado · total={self.auto_validated}")
            self.hub.publish(
                TOPIC_SCADA_STATUS,
                {
                    "event": "batch_complete",
                    "total": self.auto_validated,
                    "id_lote": self.id_lote,
                },
            )
            self.auto_target = 0   # detiene la generación
            self.auto_spawned = 0
            self.auto_validated = 0

    def _status_loop(self) -> None:
        while not self.stop_event.is_set():
            time.sleep(Timings.STATUS_PUBLISH_S)
            self.publish_status()

    def publish_status(self) -> None:
        with self.lock:
            wait_seconds = 0
            if self.amr_arrived_at:
                wait_seconds = int(time.time() - self.amr_arrived_at)
            payload = {
                "mode": self.mode,
                "id_lote": self.id_lote,
                "total_processed": self.total_processed,
                "auto_target": self.auto_target,
                "auto_spawned": self.auto_spawned,
                "auto_validated": self.auto_validated,
                "manual_remaining": self.manual_remaining,
                "expected_color": self.expected_color,
                "amr_pending_tolva": _TOLVA_NAMES[self.amr_pending_tolva] if self.amr_pending_tolva is not None else None,
                "amr_arrived_tolva": _TOLVA_NAMES[self.amr_arrived_tolva] if self.amr_arrived_tolva is not None else None,
                "amr_wait_seconds": wait_seconds,
                "tolvas": {name: self.tolva_counts[i] for i, name in enumerate(_TOLVA_NAMES)},
                "pallets": {
                    f"PALLET_{i+1}": self.pallet_counts[i] for i in range(PALLET_COUNT)
                },
            }
        self.hub.publish(TOPIC_SCADA_STATUS, payload)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Timings cercanos al sistema real (10 s de espera tolva, etc.)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Timings ultra-rápidos para humo-test (sub-segundo)",
    )
    parser.add_argument("--no-esp32", action="store_true", help="No arrancar el ESP32 mock")
    parser.add_argument("--no-camera", action="store_true", help="No arrancar la cámara mock")
    parser.add_argument("--no-delta", action="store_true", help="No arrancar el Delta mock")
    parser.add_argument("--no-amr", action="store_true", help="No arrancar el AMR mock (usa el bridge real)")
    parser.add_argument("--no-cobot", action="store_true", help="No arrancar el Cobot mock")
    args = parser.parse_args()

    if args.slow and args.fast:
        print("--slow y --fast son excluyentes", file=sys.stderr)
        return 2
    if args.slow:
        Timings.apply_preset("slow")
    elif args.fast:
        Timings.apply_preset("fast")

    log("sim", "arrancando simulador GIIROB…")
    log(
        "sim",
        f"spawn={Timings.SPAWN_INTERVAL_S}s pick={Timings.DELTA_PICK_S}s "
        f"amr={Timings.AMR_TRAVEL_S}s wait={Timings.AMR_WAIT_TOLVA_S}s "
        f"cobot={Timings.COBOT_PALLETIZE_S}s",
    )

    hub = MqttHub()
    actors_active = []
    if not args.no_camera:
        CameraSim(hub); actors_active.append("camera")
    if not args.no_delta:
        DeltaSim(hub); actors_active.append("delta")
    if not args.no_amr:
        AmrSim(hub); actors_active.append("amr")
    if not args.no_cobot:
        CobotSim(hub); actors_active.append("cobot")
    esp = None
    if not args.no_esp32:
        esp = Esp32Sim(hub); actors_active.append("esp32")
    log("sim", f"actores activos: {', '.join(actors_active) or 'ninguno'}")
    hub.start()

    log("sim", "listo. Manda comandos desde el SCADA (Ctrl-C para salir).")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("sim", "parando…")
        if esp is not None:
            esp.stop_event.set()
        hub.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
