"""Additional tabs: new Auto batch, Manual cap, and confirmations.
Allow launching batches and caps with custom parameters, and emit
manual `done` confirmations for testing or showcases."""

from __future__ import annotations

import re # re provides regular expressions to validate batch/provider formats
from typing import Optional # Optional is used to indicate that the provider can be None

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, # QComboBox is a dropdown to select the color of the cap or hopper
    QDialog, # QDialog is the base class for dialogs
    QDialogButtonBox, # QDialogButtonBox is a widget that contains the accept/cancel buttons
    QFormLayout,# QFormLayout organizes the form fields in rows with labels
    QLabel, # QLabel is used to display static text, such as field labels or hints
    QLineEdit, # QLineEdit is a single-line text field for the batch or cap ID (allows the user to type the ID)
    QMessageBox, # QMessageBox is used to show warning messages if the ID format is incorrect
    QSpinBox, # QSpinBox is a numeric field with buttons to increase/decrease the batch quantity
    QVBoxLayout, # QVBoxLayout organizes widgets vertically within the dialog
    QWidget, # QWidget is the base class for all widgets, used as a type for the parent of dialogs
)

from config import PALETTE, VALID_COLORS # Imports necessary from the config file

# Regular expressions to validate batch and provider IDs (one letter followed by 4 digits)
_LOTE_RE = re.compile(r"^[A-Z]\d{4}$")
_PROVEEDOR_RE = re.compile(r"^[A-Z]\d{4}$")

# Stylesheet common to all dialogs
def _style_dialog(dlg: QDialog) -> None:
    # dlg.setStyleSheet applies a style to the dialog and all its child widgets.
    dlg.setStyleSheet(
        f"""
        QDialog {{ background: {PALETTE.surface}; color: {PALETTE.text}; }}
        QLabel {{ color: {PALETTE.text}; }}
        QLineEdit, QSpinBox, QComboBox {{
            background: {PALETTE.surface_alt};
            color: {PALETTE.text};
            border: 1px solid {PALETTE.border};
            border-radius: 4px;
            padding: 4px 6px;
        }}
        QPushButton {{
            background: {PALETTE.accent};
            color: #1e1e2e;
            border: none;
            border-radius: 4px;
            padding: 6px 14px;
            font-weight: bold;
        }}
        QPushButton:hover {{ background: #b6f4ff; }}
        """
    )

# QDialog for adding a new Auto batch.
class NewBatchDialog(QDialog):
    """Launches an Auto batch (`gen` with quantity > 1)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        # Hierarchy of widgets:
        super().__init__(parent)
        # Title of the dialog window
        self.setWindowTitle("Nuevo lote — Auto")
        _style_dialog(self)

        # Input fields for batch ID, provider, and quantity
        self.id_lote = QLineEdit() # Enables user input
        self.id_lote.setPlaceholderText("L0042")
        self.id_lote.setMaxLength(5)

        self.proveedor = QLineEdit()
        self.proveedor.setPlaceholderText("opcional · P0003")
        self.proveedor.setMaxLength(5)

        self.quantity = QSpinBox() # Allows user selecting a number
        self.quantity.setRange(1, 100_000)
        self.quantity.setValue(100)

        # Layout of the dialog
        form = QFormLayout()
        form.addRow("ID de lote:", self.id_lote)
        form.addRow("Proveedor:", self.proveedor)
        form.addRow("Cantidad:", self.quantity)

        # Hints for the user
        hint = QLabel("Formato lote/proveedor: una letra + 4 dígitos (ej. L0042).")
        hint.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")
        hint.setWordWrap(True)

        # Buttons to accept or cancel the dialog
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        # Main layout, from top to bottom
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    # When the user clicks "OK"
    def _on_accept(self) -> None:
        id_lote = self.id_lote.text().strip().upper()
        proveedor = self.proveedor.text().strip().upper()
        if not _LOTE_RE.match(id_lote):
            QMessageBox.warning(self, "ID de lote inválido", "Formato esperado: L0042 (letra + 4 dígitos).")
            return
        if proveedor and not _PROVEEDOR_RE.match(proveedor):
            QMessageBox.warning(self, "Proveedor inválido", "Formato esperado: P0003 (letra + 4 dígitos) o vacío.")
            return
        self.accept()

    # Returns the values entered by the user, with provider as None if left empty
    def values(self) -> tuple[str, int, Optional[str]]:
        proveedor = self.proveedor.text().strip().upper() or None
        return self.id_lote.text().strip().upper(), int(self.quantity.value()), proveedor

# Dialog for setting a Manual cap with specific batch ID and color.
class ManualCapDialog(QDialog):
    """Launches a Manual cap (`gen` with quantity=1 and specific color)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tapa manual")
        _style_dialog(self)

        self.id_lote = QLineEdit()
        self.id_lote.setPlaceholderText("L0042")
        self.id_lote.setMaxLength(5)

        # Let the user select the color in a dropdown
        self.color = QComboBox()
        for c in VALID_COLORS:
            self.color.addItem(c)

        # Layout of the dialog
        form = QFormLayout()
        form.addRow("ID de lote:", self.id_lote)
        form.addRow("Color:", self.color)

        hint = QLabel("El modo se conmuta a Manual automáticamente antes de enviar el comando.")
        hint.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        id_lote = self.id_lote.text().strip().upper()
        if not _LOTE_RE.match(id_lote):
            QMessageBox.warning(self, "ID de lote inválido", "Formato esperado: L0042 (letra + 4 dígitos).")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.id_lote.text().strip().upper(), self.color.currentText()


class ConfirmDoneDialog(QDialog):
    """Dialog to manually emit the `done` confirmation of a cap."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirmar entrega de tapa")
        _style_dialog(self)

        self.id_cap = QLineEdit()
        self.id_cap.setPlaceholderText("C0005")

        self.tolva = QComboBox()
        for i in range(6):
            self.tolva.addItem(f"TOLVA_{i+1}")

        form = QFormLayout()
        form.addRow("id_cap:", self.id_cap)
        form.addRow("Tolva:", self.tolva)

        hint = QLabel("Solo usar en pruebas. En producción la confirmación la genera el Delta/HMI físico.")
        hint.setStyleSheet(f"color: {PALETTE.text_dim}; font-size: 10px;")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.id_cap.text().strip().upper(), self.tolva.currentText()
