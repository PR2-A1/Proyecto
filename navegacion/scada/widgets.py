"""Este módulo define los widgets que compondrán el SCADA,
su lógica de actualización y algunos helpers para mantener el estilo consistente.
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, QTime, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import (
    AMR_ARRIVAL_DELAY_SECS,
    AMR_TOLVA_THRESHOLD,
    COLOR_HEX,
    LOG_MAX_LINES,
    PALETTE,
    PALLET_CAPACITY,
    PALLET_COUNT,
    TOLVA_COLOR,
)
from state import SystemState


# Style Helpers

# Defines the frame style
def _frame(title: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    frame.setStyleSheet(
        f"""
        QFrame#panel {{
            background: {PALETTE.surface};
            border: 1px solid {PALETTE.border};
            border-radius: 8px;
        }}
        """
    )
    return frame

# Defines the title label style
def _title_label(text: str) -> QLabel:
    label = QLabel(text)
    f = QFont()
    f.setBold(True)
    f.setPointSize(11)
    label.setFont(f)
    label.setStyleSheet(f"color: {PALETTE.accent}; padding: 4px;")
    return label

# Defines the value label style, with an option for a bigger font size.
# Default text is "—" to indicate missing data (start state).
def _value_label(text: str = "—", *, big: bool = False) -> QLabel:
    label = QLabel(text)
    f = QFont()
    f.setBold(True)
    f.setPointSize(16 if big else 11)
    label.setFont(f)
    label.setStyleSheet(f"color: {PALETTE.text};")
    return label


# Header: modo, lote, progreso, emergencia, conexión MQTT

class HeaderPanel(QFrame):
    """Modo, lote activo, progreso, estado de emergencia y conexión MQTT."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        # Give fixed style
        self.setStyleSheet(
            f"""
            QFrame#panel {{
                background: {PALETTE.surface};
                border: 1px solid {PALETTE.border};
                border-radius: 8px;
            }}
            """
        )

        # Build the widgets
        self.mode_chip = QLabel("MODO —")
        self.mode_chip.setAlignment(Qt.AlignCenter)
        self.mode_chip.setMinimumWidth(140)
        self._style_chip(self.mode_chip, PALETTE.text_dim)

        self.lote_label = _value_label("Lote: —", big=True)

        self.total_label = QLabel("Procesadas: 0")
        self.total_label.setStyleSheet(f"color: {PALETTE.text_dim};")

        self.emergency_chip = QLabel("OPERATIVO")
        self.emergency_chip.setAlignment(Qt.AlignCenter)
        self.emergency_chip.setMinimumWidth(140)
        self._style_chip(self.emergency_chip, PALETTE.ok)

        self.mqtt_chip = QLabel("MQTT: …")
        self.mqtt_chip.setAlignment(Qt.AlignCenter)
        self.mqtt_chip.setMinimumWidth(140)
        self._style_chip(self.mqtt_chip, PALETTE.warn)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        layout.addWidget(self.mode_chip)
        layout.addWidget(self.lote_label)
        layout.addWidget(self.total_label)
        layout.addStretch()
        layout.addWidget(self.emergency_chip)
        layout.addWidget(self.mqtt_chip)

    # Static helper to style the "chips" or indicators for mode, emergency and MQTT status.
    @staticmethod
    def _style_chip(label: QLabel, color: str) -> None:
        label.setStyleSheet(
            f"""
            QLabel {{
                background: {color};
                color: #1e1e2e;
                font-weight: bold;
                padding: 6px 10px;
                border-radius: 6px;
            }}
            """
        )

    # Method to update the header fields from the system state.
    def update_from_state(self, state: SystemState) -> None:
        mode = (state.mode or "unknown").upper()
        if mode == "AUTO":
            self._style_chip(self.mode_chip, PALETTE.auto)
        elif mode == "MANUAL":
            self._style_chip(self.mode_chip, PALETTE.manual)
        else:
            self._style_chip(self.mode_chip, PALETTE.text_dim)
        self.mode_chip.setText(f"MODO {mode}")

        self.lote_label.setText(f"Lote: {state.id_lote or '—'}")
        self.total_label.setText(f"Procesadas: {state.total_processed}")

        if state.emergency_active:
            self.emergency_chip.setText(f"EMERGENCIA ({state.emergency_source or '?'})")
            self._style_chip(self.emergency_chip, PALETTE.error)
        else:
            self.emergency_chip.setText("OPERATIVO")
            self._style_chip(self.emergency_chip, PALETTE.ok)

        if state.mqtt_connected:
            self.mqtt_chip.setText("MQTT: conectado")
            self._style_chip(self.mqtt_chip, PALETTE.ok)
        else:
            self.mqtt_chip.setText("MQTT: desconectado")
            self._style_chip(self.mqtt_chip, PALETTE.error)


# Tolvas

class TolvaIndicator(QFrame):
    """Indicador individual de una tolva."""

    def __init__(self, name: str, color_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.name = name
        self.color_hex = COLOR_HEX.get(color_name, "#888888")
        self.setObjectName("tolva")
        self.setMinimumWidth(160)
        self._build()

    def _build(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#tolva {{
                background: {PALETTE.surface_alt};
                border: 2px solid {self.color_hex};
                border-radius: 8px;
            }}
            """
        )

        self.title = QLabel(f"{self.name}")
        f = QFont(); f.setBold(True); f.setPointSize(11)
        self.title.setFont(f)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"color: {self.color_hex};")

        self.count = QLabel("0")
        cf = QFont(); cf.setBold(True); cf.setPointSize(28)
        self.count.setFont(cf)
        self.count.setAlignment(Qt.AlignCenter)
        self.count.setStyleSheet(f"color: {PALETTE.text};")

        self.bar = QProgressBar()
        self.bar.setRange(0, AMR_TOLVA_THRESHOLD)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{ background: {PALETTE.bg}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {self.color_hex}; border-radius: 4px; }}
            """
        )

        self.status = QLabel("—")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.count)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)

    def update_from_state(self, state: SystemState) -> None:
        value = state.tolvas.get(self.name, 0)
        self.count.setText(str(value))
        self.bar.setValue(min(value, AMR_TOLVA_THRESHOLD))

        if state.amr_arrived_tolva == self.name:
            remaining = max(0, AMR_ARRIVAL_DELAY_SECS - state.amr_wait_seconds)
            self.status.setText(f"AMR aquí · {remaining}s")
            self.status.setStyleSheet(f"color: {PALETTE.ok}; font-weight: bold;")
        elif state.amr_pending_tolva == self.name:
            self.status.setText("AMR en ruta…")
            self.status.setStyleSheet(f"color: {PALETTE.warn}; font-weight: bold;")
        elif value >= AMR_TOLVA_THRESHOLD:
            self.status.setText("Esperando AMR")
            self.status.setStyleSheet(f"color: {PALETTE.warn};")
        else:
            self.status.setText(f"Umbral {AMR_TOLVA_THRESHOLD}")
            self.status.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")


class TolvasPanel(QFrame):
    """Panel con las 6 tolvas, su estado y colores."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.indicators: dict[str, TolvaIndicator] = {}
        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(8)
        # Creation of each tolva indicator based on the TOLVA_COLOR config, which defines the name and color of each tolva.
        for idx, (name, color) in enumerate(TOLVA_COLOR.items()):
            ind = TolvaIndicator(name, color)
            self.indicators[name] = ind
            grid.addWidget(ind, idx // 3, idx % 3)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(_title_label("Tolvas"))
        outer.addLayout(grid)

    # Method to update all tolva indicators from the system state.
    def update_from_state(self, state: SystemState) -> None:
        for ind in self.indicators.values():
            ind.update_from_state(state)


# Pallets, almost same as tolvas but with different thresholds and status logic.

class PalletIndicator(QFrame):
    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName("pallet")
        self.setStyleSheet(
            f"""
            QFrame#pallet {{
                background: {PALETTE.surface_alt};
                border: 1px solid {PALETTE.border};
                border-radius: 6px;
            }}
            """
        )

        title = QLabel(name)
        tf = QFont(); tf.setBold(True)
        title.setFont(tf)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {PALETTE.text};")

        self.count = QLabel("0 / 12")
        self.count.setAlignment(Qt.AlignCenter)
        cf = QFont(); cf.setPointSize(14); cf.setBold(True)
        self.count.setFont(cf)
        self.count.setStyleSheet(f"color: {PALETTE.text};")

        self.bar = QProgressBar()
        self.bar.setRange(0, PALLET_CAPACITY)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setStyleSheet(
            f"""
            QProgressBar {{ background: {PALETTE.bg}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {PALETTE.accent}; border-radius: 4px; }}
            """
        )

        self.status = QLabel("abierto")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        layout.addWidget(title)
        layout.addWidget(self.count)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)

    def update_from_state(self, state: SystemState) -> None:
        value = state.pallets.get(self.name, 0)
        self.count.setText(f"{value} / {PALLET_CAPACITY}")
        self.bar.setValue(min(value, PALLET_CAPACITY))
        if value >= PALLET_CAPACITY:
            self.status.setText("LLENO · retirar")
            self.status.setStyleSheet(f"color: {PALETTE.error}; font-weight: bold;")
        elif value > 0:
            self.status.setText("paletizando")
            self.status.setStyleSheet(f"color: {PALETTE.warn};")
        else:
            self.status.setText("abierto")
            self.status.setStyleSheet(f"color: {PALETTE.text_dim};")


class PalletsPanel(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.indicators: dict[str, PalletIndicator] = {}
        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(8)
        for i in range(PALLET_COUNT):
            name = f"PALLET_{i+1}"
            ind = PalletIndicator(name)
            self.indicators[name] = ind
            # Place the widget in a 3-column grid layout
            grid.addWidget(ind, i // 3, i % 3)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(_title_label("Pallets"))
        outer.addLayout(grid)

    def update_from_state(self, state: SystemState) -> None:
        for ind in self.indicators.values():
            ind.update_from_state(state)


# AMR / Cobot / Camera

class AmrPanel(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.status_value = _value_label("idle", big=True)
        self.location_value = _value_label("—")
        self.target_value = _value_label("—")
        self.wait_value = _value_label("—")

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel("Estado:"), 0, 0); grid.addWidget(self.status_value, 0, 1)
        grid.addWidget(QLabel("Posición:"), 1, 0); grid.addWidget(self.location_value, 1, 1)
        grid.addWidget(QLabel("Destino:"), 2, 0); grid.addWidget(self.target_value, 2, 1)
        grid.addWidget(QLabel("Espera tolva (s):"), 3, 0); grid.addWidget(self.wait_value, 3, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(_title_label("AMR"))
        outer.addLayout(grid)

    def update_from_state(self, state: SystemState) -> None:
        self.status_value.setText(state.amr_last_status or "idle")
        self.location_value.setText(state.amr_last_location or "—")

        # Priority of destination: active destination (goto) > pending tolva > arrived tolva.
        destination = (
            state.amr_active_destination
            or state.amr_pending_tolva
            or state.amr_arrived_tolva
            or "—"
        )
        self.target_value.setText(destination)

        if state.amr_arrived_tolva:
            remaining = max(0, AMR_ARRIVAL_DELAY_SECS - state.amr_wait_seconds)
            self.wait_value.setText(f"{remaining} restantes")
        else:
            self.wait_value.setText("—")

        if state.amr_last_status == "active":
            self.status_value.setStyleSheet(f"color: {PALETTE.ok}; font-weight: bold;")
        elif state.amr_last_status == "navigating":
            self.status_value.setStyleSheet(f"color: {PALETTE.warn}; font-weight: bold;")
        elif state.amr_last_status == "arrived":
            self.status_value.setStyleSheet(f"color: {PALETTE.ok}; font-weight: bold;")
        elif state.amr_last_status == "failed":
            self.status_value.setStyleSheet(f"color: {PALETTE.error}; font-weight: bold;")
        else:
            self.status_value.setStyleSheet(f"color: {PALETTE.text_dim}; font-weight: bold;")


class CobotPanel(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.busy_value = _value_label("idle", big=True)
        self.pallet_value = _value_label("—")

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.addWidget(QLabel("Estado:"), 0, 0); grid.addWidget(self.busy_value, 0, 1)
        grid.addWidget(QLabel("Último pallet:"), 1, 0); grid.addWidget(self.pallet_value, 1, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(_title_label("Cobot"))
        outer.addLayout(grid)

    def update_from_state(self, state: SystemState) -> None:
        if state.cobot_in_progress:
            self.busy_value.setText("paletizando")
            self.busy_value.setStyleSheet(f"color: {PALETTE.warn}; font-weight: bold;")
        else:
            self.busy_value.setText("idle")
            self.busy_value.setStyleSheet(f"color: {PALETTE.text_dim}; font-weight: bold;")
        self.pallet_value.setText(state.cobot_last_pallet or "—")


class CameraPanel(QFrame):
    """Panel de visión: color esperado + últimas detecciones."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.expected_value = _value_label("—", big=True)
        self.last_detection = _value_label("—")
        self.discarded = 0
        self.discarded_label = _value_label("0")

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.addWidget(QLabel("Color esperado:"), 0, 0); grid.addWidget(self.expected_value, 0, 1)
        grid.addWidget(QLabel("Última detección:"), 1, 0); grid.addWidget(self.last_detection, 1, 1)
        grid.addWidget(QLabel("Descartadas:"), 2, 0); grid.addWidget(self.discarded_label, 2, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addWidget(_title_label("Cámara"))
        outer.addLayout(grid)

    def update_from_state(self, state: SystemState) -> None:
        color = state.expected_color or "—"
        self.expected_value.setText(color)
        if color in COLOR_HEX:
            self.expected_value.setStyleSheet(
                f"color: {COLOR_HEX[color]}; font-weight: bold; font-size: 18px;"
            )
        else:
            self.expected_value.setStyleSheet(f"color: {PALETTE.text_dim};")

    def on_camera_data(self, payload: dict) -> None:
        precision = payload.get("precision")
        if isinstance(precision, (int, float)) and precision <= 0.95:
            self.discarded += 1
            self.discarded_label.setText(str(self.discarded))
            return
        color = payload.get("color", "?")
        id_cap = payload.get("id_cap", "?")
        x = payload.get("x"); y = payload.get("y")
        self.last_detection.setText(f"{id_cap} · {color} @ ({x}, {y})")


# Log de eventos

class LogPanel(QFrame):
    """Log de eventos con filtros de nivel."""

    LEVEL_COLORS = {
        "info": PALETTE.text,
        "rx": PALETTE.accent,
        "tx": PALETTE.auto,
        "warn": PALETTE.warn,
        "error": PALETTE.error,
        "event": PALETTE.ok,
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setStyleSheet(
            f"""
            QTextEdit {{
                background: {PALETTE.bg};
                color: {PALETTE.text};
                border: none;
                font-family: 'Monospace';
                font-size: 11px;
                padding: 6px;
            }}
            """
        )

        clear_btn = QPushButton("Limpiar")
        clear_btn.clicked.connect(self.view.clear)

        header = QHBoxLayout()
        header.addWidget(_title_label("Log de eventos"))
        header.addStretch()
        header.addWidget(clear_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.addLayout(header)
        outer.addWidget(self.view)

    def append(self, level: str, text: str) -> None:
        color = self.LEVEL_COLORS.get(level, PALETTE.text)
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        # Limita el número de líneas para no crecer indefinidamente.
        if self.view.document().blockCount() > LOG_MAX_LINES:
            cursor = self.view.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self.view.append(f'<span style="color:{PALETTE.text_dim};">[{timestamp}]</span> '
                          f'<span style="color:{color};">{level.upper():<5}</span> {text}')
