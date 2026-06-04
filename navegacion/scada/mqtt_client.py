"""Cliente MQTT aislado en hilo paho, comunica con la UI por señales Qt.

Diseño: paho corre su propio loop en `loop_start()`. Sus callbacks NO pueden
tocar widgets Qt — por eso traducen cada evento a un `pyqtSignal`, que Qt
entrega en el hilo principal vía la cola de eventos.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import paho.mqtt.client as mqtt
from PyQt5.QtCore import QObject, pyqtSignal

from config import (
    MQTT_CLIENT_ID_PREFIX,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_PORT,
    SUBSCRIBE_TOPICS,
    TOPIC_EMERGENCY_ACTION,
    TOPIC_SCADA_ACTION,
    TOPIC_SCADA_STATUS,
)


class MqttBridge(QObject):
    """Envuelve paho-mqtt y expone señales tipadas a la capa Qt."""

    # status: bool connected, str info
    connection_changed = pyqtSignal(bool, str)

    # topic, payload (dict already parsed)
    message_received = pyqtSignal(str, dict)

    # topic, payload raw
    raw_message = pyqtSignal(str, str)

    # Log
    log = pyqtSignal(str, str)  # (level, message)

    def __init__(
        self,
        host: str = MQTT_HOST,
        port: int = MQTT_PORT,
        keepalive: int = MQTT_KEEPALIVE,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._port = port
        self._keepalive = keepalive
        client_id = f"{MQTT_CLIENT_ID_PREFIX}{uuid.uuid4().hex[:8]}"
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    # API pública

    def start(self) -> None:
        """Launches connection and paho loop in a background thread."""
        self.log.emit("info", f"Conectando a {self._host}:{self._port}…")
        try:
            self._client.connect_async(self._host, self._port, self._keepalive)
            self._client.loop_start()
        except Exception as exc:
            self.log.emit("error", f"Fallo al iniciar MQTT: {exc}")
            self.connection_changed.emit(False, str(exc))

    def stop(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def publish(self, topic: str, payload: dict, qos: int = 1) -> bool:
        """Publishes a JSON payload to the specified topic. Returns True if paho accepted the operation."""
        try:
            data = json.dumps(payload, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            self.log.emit("error", f"JSON inválido para {topic}: {exc}")
            return False

        result = self._client.publish(topic, data, qos=qos)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.emit("error", f"Publicación fallida en {topic} (rc={result.rc})")
            return False
        self.log.emit("tx", f"→ {topic}: {data}")
        return True

    # High-level helper methods for SCADA commands

    def cmd_gen_auto(self, id_lote: str, quantity: int, proveedor: Optional[str] = None) -> bool:
        payload: dict[str, Any] = {"cmd": "gen", "id_lote": id_lote, "quantity": int(quantity)}
        if proveedor:
            payload["proveedor"] = proveedor
        return self.publish(TOPIC_SCADA_ACTION, payload)

    def cmd_gen_manual(self, id_lote: str, color: str) -> bool:
        payload = {"cmd": "gen", "id_lote": id_lote, "color": color, "quantity": 1}
        return self.publish(TOPIC_SCADA_ACTION, payload)

    def cmd_set_mode(self, mode: str) -> bool:
        return self.publish(TOPIC_SCADA_ACTION, {"cmd": "set_mode", "mode": mode})

    def cmd_status(self) -> bool:
        return self.publish(TOPIC_SCADA_ACTION, {"cmd": "status"})

    def cmd_reset(self) -> bool:
        return self.publish(TOPIC_SCADA_ACTION, {"cmd": "reset"})

    def cmd_done(self, id_cap: str, tolva: str) -> bool:
        # El SCADA virtual emite la confirmación en el mismo topic de status.
        return self.publish(TOPIC_SCADA_STATUS, {"cmd": "done", "id_cap": id_cap, "tolva": tolva})

    def cmd_emergency_stop(self) -> bool:
        return self.publish(TOPIC_EMERGENCY_ACTION, {"cmd": "estop", "source": "SCADA"})

    def cmd_emergency_resume(self) -> bool:
        return self.publish(TOPIC_EMERGENCY_ACTION, {"cmd": "resume", "source": "SCADA"})

    # Callbacks paho

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.log.emit("error", f"Broker rechazó conexión (rc={rc})")
            self.connection_changed.emit(False, f"rc={rc}")
            return
        # Short delay to ensure the connection is fully stablished
        time.sleep(0.2)
        for topic in SUBSCRIBE_TOPICS:
            client.subscribe(topic, qos=1)
        self.log.emit("info", f"Conectado · suscrito a {len(SUBSCRIBE_TOPICS)} topics")
        self.connection_changed.emit(True, "OK")

    def _on_disconnect(self, client, userdata, rc):
        self.log.emit("warn", f"Desconectado del broker (rc={rc})")
        self.connection_changed.emit(False, f"rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            text = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            self.log.emit("warn", f"Payload no-UTF8 en {msg.topic}")
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self.raw_message.emit(msg.topic, text)
            return

        if not isinstance(data, dict):
            self.raw_message.emit(msg.topic, text)
            return

        self.log.emit("rx", f"← {msg.topic}: {text}")
        self.message_received.emit(msg.topic, data)
