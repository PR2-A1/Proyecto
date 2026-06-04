"""Ventana principal del SCADA: ensambla widgets, controles y bridge MQTT.

Flujo:
    MQTT (paho) → señal Qt → handler en hilo principal → SystemState.apply_X →
    update_from_state() en cada panel.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtWidgets import (
    QAction,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from config import (
    PALETTE,
    STATUS_REQUEST_INTERVAL_MS,
    TOPIC_AMR_ACTION,
    TOPIC_AMR_STATUS,
    TOPIC_CAMERA_DATA,
    TOPIC_COBOT_ACTION,
    TOPIC_COBOT_STATUS,
    TOPIC_DB_PUSH,
    TOPIC_EMERGENCY_STATUS,
    TOPIC_SCADA_STATUS,
)
from dialogs import ConfirmDoneDialog, ManualCapDialog, NewBatchDialog
from mqtt_client import MqttBridge
from state import SystemState
from widgets import (
    AmrPanel,
    CameraPanel,
    CobotPanel,
    HeaderPanel,
    LogPanel,
    PalletsPanel,
    TolvasPanel,
)


class ControlsPanel(QFrame):
    """Botonera lateral: lanzar lote, manual, status, reset, emergencia."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; border-radius: 8px; }}"
        )

        # Create button instances
        self.btn_new_batch = self._button("Nuevo lote (Auto)", PALETTE.auto)
        self.btn_manual_cap = self._button("Tapa manual", PALETTE.manual)
        self.btn_set_auto = self._button("Modo Auto", PALETTE.surface_alt, dark_text=False)
        self.btn_set_manual = self._button("Modo Manual", PALETTE.surface_alt, dark_text=False)
        self.btn_status = self._button("Solicitar estado", PALETTE.accent)
        self.btn_done = self._button("Confirmar tapa (debug)", PALETTE.surface_alt, dark_text=False)
        self.btn_reset = self._button("Reset", PALETTE.warn)
        self.btn_emergency = self._button("EMERGENCIA", PALETTE.error)
        self.btn_resume = self._button("Reanudar", PALETTE.ok)
        self.btn_resume.setEnabled(False)

        # Set fixed height for all buttons
        for b in self._all_buttons():
            b.setMinimumHeight(36)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Emergency button bigger
        self.btn_emergency.setMinimumHeight(54)
        fnt = self.btn_emergency.font(); fnt.setPointSize(13); fnt.setBold(True)
        self.btn_emergency.setFont(fnt)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.btn_new_batch)
        layout.addWidget(self.btn_manual_cap)
        layout.addSpacing(6)
        layout.addWidget(self.btn_set_auto)
        layout.addWidget(self.btn_set_manual)
        layout.addSpacing(6)
        layout.addWidget(self.btn_status)
        layout.addWidget(self.btn_done)
        layout.addWidget(self.btn_reset)
        layout.addStretch()
        layout.addWidget(self.btn_emergency)
        layout.addWidget(self.btn_resume)

    # Static helper to create styled buttons
    @staticmethod
    def _button(text: str, color: str, *, dark_text: bool = True) -> QPushButton:
        b = QPushButton(text)
        fg = "#1e1e2e" if dark_text else PALETTE.text
        b.setStyleSheet(
            f"""
            QPushButton {{
                background: {color};
                color: {fg};
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton:disabled {{ background: {PALETTE.text_dim}; color: {PALETTE.surface}; }}
            QPushButton:hover:!disabled {{ border: 2px solid {PALETTE.text}; }}
            """
        )
        return b

    # Helper to get all buttons for batch styling
    def _all_buttons(self) -> list[QPushButton]:
        return [
            self.btn_new_batch, self.btn_manual_cap,
            self.btn_set_auto, self.btn_set_manual,
            self.btn_status, self.btn_done, self.btn_reset,
            self.btn_emergency, self.btn_resume,
        ]

    # Method for enabling/disabling buttons based on operational state and MQTT connection
    def set_operational(self, operational: bool, mqtt_connected: bool) -> None:
        """Habilita/deshabilita botones según emergencia y conexión."""
        # On Emergency, just enable the emergency resume button. If MQTT is disconnected, disable all except maybe emergency stop.
        normal_buttons = [
            self.btn_new_batch, self.btn_manual_cap,
            self.btn_set_auto, self.btn_set_manual,
            self.btn_status, self.btn_done, self.btn_reset,
        ]
        for b in normal_buttons:
            b.setEnabled(operational and mqtt_connected)
        self.btn_emergency.setEnabled(operational and mqtt_connected)
        self.btn_resume.setEnabled(not operational and mqtt_connected)

# Main window for the SCADA application. Contains all panels, status bar, and MQTT bridge. Updates UI based on SystemState.
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SCADA GIIROB · PR2-A1")
        self.resize(1400, 850)

        # Status of the system, updated from MQTT messages and reflected in the UI.
        self.state = SystemState()

        # Dark palette
        self._apply_dark_palette()

        # Widgets
        self.header = HeaderPanel()
        self.tolvas_panel = TolvasPanel()
        self.pallets_panel = PalletsPanel()
        self.amr_panel = AmrPanel()
        self.cobot_panel = CobotPanel()
        self.camera_panel = CameraPanel()
        self.log_panel = LogPanel()
        self.controls = ControlsPanel()

        # Layout
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(8)

        # Main column (status panels)
        main_col = QGridLayout()
        main_col.setSpacing(8)
        main_col.addWidget(self.tolvas_panel, 0, 0, 1, 2)
        main_col.addWidget(self.pallets_panel, 1, 0, 1, 2)
        main_col.addWidget(self.amr_panel, 2, 0)
        main_col.addWidget(self.cobot_panel, 2, 1)
        main_col.addWidget(self.camera_panel, 3, 0, 1, 2)
        main_col.setRowStretch(0, 2)
        main_col.setRowStretch(1, 2)
        main_col.setRowStretch(2, 1)
        main_col.setRowStretch(3, 1)

        body.addLayout(main_col, 3)

        # Right column (controls + log)
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(self.controls, 0)
        right_col.addWidget(self.log_panel, 1)
        body.addLayout(right_col, 2)

        outer.addLayout(body, 1)
        self.setCentralWidget(central)

        # Bridge MQTT
        self.mqtt = MqttBridge(parent=self)
        self.mqtt.connection_changed.connect(self._on_connection_changed)
        self.mqtt.message_received.connect(self._on_message)
        self.mqtt.log.connect(self.log_panel.append)

        # Button hanflers, connect is a method of QPushButton that connects a click to a handler function.
        self.controls.btn_new_batch.clicked.connect(self._on_new_batch)
        self.controls.btn_manual_cap.clicked.connect(self._on_manual_cap)
        self.controls.btn_set_auto.clicked.connect(lambda: self.mqtt.cmd_set_mode("auto"))
        self.controls.btn_set_manual.clicked.connect(lambda: self.mqtt.cmd_set_mode("manual"))
        self.controls.btn_status.clicked.connect(self.mqtt.cmd_status)
        self.controls.btn_done.clicked.connect(self._on_confirm_done)
        self.controls.btn_reset.clicked.connect(self._on_reset)
        self.controls.btn_emergency.clicked.connect(self._on_emergency_stop)
        self.controls.btn_resume.clicked.connect(self._on_emergency_resume)

        # Periodic refresh of status
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(STATUS_REQUEST_INTERVAL_MS)
        self.status_timer.timeout.connect(self.mqtt.cmd_status)

        # Status bar
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Conectando al broker MQTT…")
        self._refresh_ui()

        # Start MQTT
        self.mqtt.start()

    # Slots Qt (hilo principal)

    # If MQTT connection changes, update UI and status bar.
    def _on_connection_changed(self, connected: bool, info: str) -> None:
        self.state.mqtt_connected = connected
        if connected:
            self.statusBar().showMessage("Conectado al broker. Solicitando estado…")
            # Status after a short delay
            QTimer.singleShot(500, self.mqtt.cmd_status)
            self.status_timer.start()
        else:
            self.statusBar().showMessage(f"Sin conexión MQTT ({info})")
            self.status_timer.stop()
        self._refresh_ui()

    # Handle incoming messages form MQTT, based on topic and payload.
    def _on_message(self, topic: str, payload: dict) -> None:
        # Filter by topic
        if topic == TOPIC_SCADA_STATUS:
            # Get the payload event and apply accordingly.
            event = payload.get("event")
            if event == "batch_complete":
                self.log_panel.append(
                    "event",
                    f"Lote completado: {payload.get('id_lote') or '?'} "
                    f"(total {payload.get('total') or '?'})",
                )
            elif event == "pallet_full":
                pallet = payload.get("id_palet") or payload.get("pallet_id") or "?"
                self.log_panel.append("event", f"Pallet lleno: {pallet} — retirar")
                QMessageBox.information(self, "Pallet lleno", f"El pallet {pallet} está lleno. Retírelo.")
            else:
                self.state.apply_scada_status(payload)
        # Repeat topic check
        elif topic == TOPIC_AMR_ACTION:
            self.state.apply_amr_action(payload)
        elif topic == TOPIC_AMR_STATUS:
            self.state.apply_amr_status(payload)
        elif topic == TOPIC_COBOT_ACTION:
            # El SCADA observa la orden al cobot para reflejar "paletizando".
            self.state.cobot_in_progress = True
            pallet = payload.get("id_pallet") or payload.get("pallet_id")
            if isinstance(pallet, str):
                self.state.cobot_last_pallet = pallet
        elif topic == TOPIC_COBOT_STATUS:
            self.state.apply_cobot_status(payload)
        elif topic == TOPIC_EMERGENCY_STATUS:
            previous = self.state.emergency_active
            self.state.apply_emergency_status(payload)
            if self.state.emergency_active and not previous:
                self.log_panel.append(
                    "error",
                    f"EMERGENCIA activa (origen: {self.state.emergency_source})",
                )
            elif previous and not self.state.emergency_active:
                self.log_panel.append(
                    "event",
                    f"Emergencia desactivada (origen: {self.state.emergency_source})",
                )
        elif topic == TOPIC_CAMERA_DATA:
            self.camera_panel.on_camera_data(payload)
        elif topic == TOPIC_DB_PUSH:
            event = payload.get("event")
            if event:
                self.log_panel.append("event", f"DB push · {event} · {payload.get('id_caja') or ''}")
        self._refresh_ui()

    # Button handlers
    def _on_new_batch(self) -> None:
        dlg = NewBatchDialog(self)
        #  Check if the dialog was accepted or rejected.
        if dlg.exec_() != dlg.Accepted:
            return
        id_lote, quantity, proveedor = dlg.values()
        # We force Auto mode, as the ESP will ignore the comand if it's in manual mode.
        self.mqtt.cmd_set_mode("auto")
        QTimer.singleShot(200, lambda: self.mqtt.cmd_gen_auto(id_lote, quantity, proveedor))

    def _on_manual_cap(self) -> None:
        dlg = ManualCapDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        id_lote, color = dlg.values()
        self.mqtt.cmd_set_mode("manual")
        QTimer.singleShot(200, lambda: self.mqtt.cmd_gen_manual(id_lote, color))

    def _on_confirm_done(self) -> None:
        dlg = ConfirmDoneDialog(self)
        if dlg.exec_() != dlg.Accepted:
            return
        id_cap, tolva = dlg.values()
        if not id_cap:
            return
        self.mqtt.cmd_done(id_cap, tolva)

    def _on_reset(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Confirmar reset",
            "Esto reinicia todos los contadores (tolvas, pallets, lote activo).\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.mqtt.cmd_reset()

    def _on_emergency_stop(self) -> None:
        confirm = QMessageBox.question(
            self,
            "PARADA DE EMERGENCIA",
            "¿Confirma la parada de emergencia? El sistema dejará de aceptar órdenes.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.mqtt.cmd_emergency_stop()

    def _on_emergency_resume(self) -> None:
        self.mqtt.cmd_emergency_resume()

    # Refresh of the UI
    def _refresh_ui(self) -> None:
        self.header.update_from_state(self.state)
        self.tolvas_panel.update_from_state(self.state)
        self.pallets_panel.update_from_state(self.state)
        self.amr_panel.update_from_state(self.state)
        self.cobot_panel.update_from_state(self.state)
        self.camera_panel.update_from_state(self.state)
        self.controls.set_operational(
            operational=not self.state.emergency_active,
            mqtt_connected=self.state.mqtt_connected,
        )


    def _apply_dark_palette(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow {{ background: {PALETTE.bg}; }}
            QWidget {{ color: {PALETTE.text}; background: {PALETTE.bg}; }}
            QLabel {{ background: transparent; }}
            QStatusBar {{ color: {PALETTE.text_dim}; background: {PALETTE.bg}; }}
            QToolTip {{ color: {PALETTE.text}; background-color: {PALETTE.surface_alt}; border: 1px solid {PALETTE.border}; }}
            """
        )

    def closeEvent(self, event) -> None:
        self.mqtt.stop()
        super().closeEvent(event)
