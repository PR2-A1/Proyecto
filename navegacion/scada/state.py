"""Modelo de estado del SCADA — réplica del ControlState del firmware.

El estado se actualiza al recibir mensajes en `scada/status`. La UI lee de aquí
en cada refresco.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from config import PALLET_COUNT, TOLVA_COLOR


class SystemState:
    """Réplica local del ControlState del firmware. Todos los campos se
    inicializan en el constructor — sin dataclass, para mantener el mismo
    estilo de inicialización que el resto de clases del proyecto."""

    def __init__(self) -> None:
        # Header
        self.mode: str = "unknown"   # auto / manual / unknown
        self.id_lote: Optional[str] = None
        self.total_processed: int = 0

        # Auto
        self.auto_target: int = 0
        self.auto_spawned: int = 0
        self.auto_validated: int = 0

        # Manual
        self.manual_remaining: int = 0
        self.expected_color: Optional[str] = None

        # AMR
        self.amr_pending_tolva: Optional[str] = None
        self.amr_arrived_tolva: Optional[str] = None
        self.amr_wait_seconds: int = 0
        # navigating / active / inactive / arrived / failed / idle
        self.amr_last_status: str = "idle"
        self.amr_last_location: str = ""
        self.amr_active_destination: Optional[str] = None

        # Cobot
        self.cobot_in_progress: bool = False
        self.cobot_last_pallet: Optional[str] = None

        # Tolvas / pallets
        self.tolvas: dict = {k: 0 for k in TOLVA_COLOR}
        self.pallets: dict = {f"PALLET_{i+1}": 0 for i in range(PALLET_COUNT)}

        # Emergency
        self.emergency_active: bool = False
        self.emergency_source: Optional[str] = None
        self.emergency_reason: Optional[str] = None

        # Conexion
        self.mqtt_connected: bool = False
        self.last_status_update: Optional[datetime] = None

    # Message actualization methods

    # Refreshes the satus form the SCARA messages.SS
    def apply_scada_status(self, payload: dict) -> None:
        """Aplica el bloque de estado completo publicado por el ESP32."""
        # Get the mode and normalize to lowercase.
        mode = payload.get("mode")
        if isinstance(mode, str):
            self.mode = mode.lower()

        # Now actualize the fields if they are present in the new payload.
        if "id_lote" in payload:
            self.id_lote = payload.get("id_lote") or None
        if "total_processed" in payload:
            self.total_processed = int(payload.get("total_processed") or 0)

        if "auto_target" in payload:
            self.auto_target = int(payload.get("auto_target") or 0)
        if "auto_spawned" in payload:
            self.auto_spawned = int(payload.get("auto_spawned") or 0)
        if "auto_validated" in payload:
            self.auto_validated = int(payload.get("auto_validated") or 0)

        if "manual_remaining" in payload:
            self.manual_remaining = int(payload.get("manual_remaining") or 0)
        if "expected_color" in payload:
            self.expected_color = payload.get("expected_color") or None

        if "amr_pending_tolva" in payload:
            self.amr_pending_tolva = _normalize_tolva(payload.get("amr_pending_tolva"))
        if "amr_arrived_tolva" in payload:
            self.amr_arrived_tolva = _normalize_tolva(payload.get("amr_arrived_tolva"))
        if "amr_wait_seconds" in payload:
            self.amr_wait_seconds = int(payload.get("amr_wait_seconds") or 0)

        # Actualize tolvas and pallets if they are present int he payload.
        tolvas = payload.get("tolvas")
        if isinstance(tolvas, dict):
            # Key is the tolva name and value is the count.
            for key, value in tolvas.items():
                # Normalize to uppercase
                norm = key.upper()
                # If it is a known tolva, update the count.
                if norm in self.tolvas:
                    self.tolvas[norm] = int(value or 0)

        # Same with pallets.
        pallets = payload.get("pallets")
        if isinstance(pallets, dict):
            for key, value in pallets.items():
                norm = key.upper()
                if norm in self.pallets:
                    self.pallets[norm] = int(value or 0)

        # Timestamp
        self.last_status_update = datetime.now()

    # AMR action and status updates
    def apply_amr_action(self, payload: dict) -> None:
        """Captura un `goto` circulando por amr/action — marca destino."""
        cmd = (payload.get("cmd") or "").lower()
        location = payload.get("location")
        if cmd != "goto" or not isinstance(location, str) or not location.strip():
            return
        self.amr_active_destination = location.strip().upper()
        self.amr_last_status = "navigating"

    def apply_amr_status(self, payload: dict) -> None:
        status = payload.get("status")
        location = payload.get("location") or ""
        if isinstance(status, str):
            self.amr_last_status = status.lower()
        if isinstance(location, str):
            self.amr_last_location = location

        # Al llegar (o si falla la navegación) el destino activo deja de tener sentido.
        if self.amr_last_status in ("arrived", "failed"):
            self.amr_active_destination = None

    # Cobot updates
    def apply_cobot_status(self, payload: dict) -> None:
        status = payload.get("status")
        pallet = payload.get("id_pallet") or payload.get("pallet_id")
        if isinstance(status, str) and status.lower() == "completed":
            self.cobot_in_progress = False
            if isinstance(pallet, str):
                self.cobot_last_pallet = pallet

    # Emergency updates
    def apply_emergency_status(self, payload: dict) -> None:
        status = (payload.get("status") or "").lower()
        self.emergency_active = status == "emergency_active"
        self.emergency_source = payload.get("source") or payload.get("device") or payload.get("sensor")
        self.emergency_reason = payload.get("reason")

# Helper function for normalizing tolva names, as they can come in different formats from the payload.
def _normalize_tolva(value) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()
