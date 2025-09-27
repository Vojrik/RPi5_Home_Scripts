"""Main Qt application for managing disk check services and schedules."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List

from PySide6 import QtCore, QtWidgets

from . import config as config_module
from .cron_manager import apply_cron, build_cron_entries
from .service_manager import get_service_state, set_service_enabled, systemctl_available


class ServiceRow(QtWidgets.QWidget):
    """Row widget holding one service toggle."""

    statusChanged = QtCore.Signal()

    def __init__(self, service: Dict[str, str], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._building = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.checkbox = QtWidgets.QCheckBox(service["display_name"])
        self.checkbox.stateChanged.connect(self._on_state_changed)
        layout.addWidget(self.checkbox, stretch=1)

        self.status_label = QtWidgets.QLabel("…")
        self.status_label.setMinimumWidth(120)
        layout.addWidget(self.status_label)

        self.detail_label = QtWidgets.QLabel(service.get("service", ""))
        self.detail_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.detail_label)

        self.refresh()

    @property
    def service_name(self) -> str:
        return self._service["service"]

    def refresh(self) -> None:
        state = get_service_state(self.service_name)
        try:
            self._building = True
            if state.enabled is None:
                self.checkbox.setCheckState(QtCore.Qt.PartiallyChecked)
                self.checkbox.setEnabled(False)
            else:
                self.checkbox.setEnabled(True)
                self.checkbox.setChecked(state.enabled)
        finally:
            self._building = False

        if state.error:
            self.status_label.setText(f"Chyba: {state.error}")
            self.status_label.setStyleSheet("color: #d9534f")
        else:
            if state.active:
                self.status_label.setText("Aktivní")
                self.status_label.setStyleSheet("color: #5cb85c")
            elif state.active is False:
                self.status_label.setText("Zastaveno")
                self.status_label.setStyleSheet("color: #f0ad4e")
            else:
                self.status_label.setText("Neznámý stav")
                self.status_label.setStyleSheet("color: #999999")
        self.statusChanged.emit()

    def _on_state_changed(self, state: int) -> None:
        if self._building:
            return
        desired = state == QtCore.Qt.Checked
        try:
            result = set_service_enabled(self.service_name, desired)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Chyba", str(exc))
            self.refresh()
            return
        if result.returncode != 0:
            QtWidgets.QMessageBox.critical(
                self,
                "Chyba",
                f"Nepodařilo se {'zapnout' if desired else 'vypnout'} službu {self.service_name}.\n\n"
                f"systemctl výstup:\n{result.stderr or result.stdout}",
            )
        self.refresh()


class ServicesTab(QtWidgets.QWidget):
    """Tab containing service toggles."""

    def __init__(self, services: List[Dict[str, str]], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)

        if not systemctl_available():
            banner = QtWidgets.QLabel(
                "<b>systemctl není k dispozici.</b> Změna stavu služeb nebude fungovat na tomto zařízení."
            )
            banner.setWordWrap(True)
            layout.addWidget(banner)

        categories: Dict[str, List[Dict[str, str]]] = {}
        for service in services:
            categories.setdefault(service.get("category", "jiné"), []).append(service)

        for category, items in categories.items():
            group = QtWidgets.QGroupBox(category.capitalize())
            group_layout = QtWidgets.QVBoxLayout(group)
            for service in items:
                row = ServiceRow(service)
                group_layout.addWidget(row)
            group_layout.addStretch()
            layout.addWidget(group)

        layout.addStretch()

        refresh_button = QtWidgets.QPushButton("Aktualizovat stavy")
        refresh_button.clicked.connect(self.refresh)
        layout.addWidget(refresh_button, alignment=QtCore.Qt.AlignRight)

    def refresh(self) -> None:
        for row in self.findChildren(ServiceRow):
            row.refresh()


class DiskChecksTab(QtWidgets.QWidget):
    """Tab with configuration for SMART and RAID checks."""

    def __init__(self, config: Dict[str, object], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        self.log_group = self._build_log_group()
        layout.addWidget(self.log_group)

        self.email_group = self._build_email_group()
        layout.addWidget(self.email_group)

        self.smart_group = self._build_smart_group()
        layout.addWidget(self.smart_group)

        self.schedule_group = self._build_schedule_group()
        layout.addWidget(self.schedule_group)

        self.manual_group = self._build_manual_group()
        layout.addWidget(self.manual_group)

        buttons_layout = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton("Aktualizovat náhled cron")
        self.preview_button.clicked.connect(self.update_cron_preview)
        buttons_layout.addWidget(self.preview_button)

        self.apply_button = QtWidgets.QPushButton("Uložit a aplikovat cron")
        self.apply_button.clicked.connect(self.save_and_apply)
        buttons_layout.addWidget(self.apply_button)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        self.cron_preview = QtWidgets.QPlainTextEdit()
        self.cron_preview.setReadOnly(True)
        layout.addWidget(self.cron_preview)

        self.output_box = QtWidgets.QPlainTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setPlaceholderText("Výstup skriptů se zobrazí zde…")
        layout.addWidget(self.output_box)

        self.update_cron_preview()

    # region builders
    def _build_log_group(self) -> QtWidgets.QGroupBox:
        data = self._config.get("log_settings", {})
        group = QtWidgets.QGroupBox("Cesty a logování")
        form = QtWidgets.QFormLayout(group)

        script_dir = str(self._config.get("script_directory", config_module.DEFAULT_CONFIG["script_directory"]))
        self.script_dir_edit = QtWidgets.QLineEdit(script_dir)
        form.addRow("Adresář skriptů:", self._with_browse(self.script_dir_edit))

        self.primary_log_edit = QtWidgets.QLineEdit(data.get("primary", ""))
        form.addRow("Primární složka:", self._with_browse(self.primary_log_edit))

        self.fallback_log_edit = QtWidgets.QLineEdit(data.get("fallback", ""))
        form.addRow("Fallback složka:", self._with_browse(self.fallback_log_edit))

        self.desktop_symlink_check = QtWidgets.QCheckBox("Vytvářet symlinky na ploše")
        self.desktop_symlink_check.setChecked(bool(data.get("desktop_symlinks", False)))
        form.addRow("", self.desktop_symlink_check)
        return group

    def _build_email_group(self) -> QtWidgets.QGroupBox:
        data = self._config.get("email", {})
        group = QtWidgets.QGroupBox("E-mailové notifikace")
        form = QtWidgets.QFormLayout(group)

        self.recipient_edit = QtWidgets.QLineEdit(data.get("recipient", ""))
        form.addRow("Příjemce:", self.recipient_edit)

        self.subject_edit = QtWidgets.QLineEdit(data.get("subject_template", ""))
        form.addRow("Předmět:", self.subject_edit)

        self.send_success_check = QtWidgets.QCheckBox("Posílat i úspěšné reporty")
        self.send_success_check.setChecked(bool(data.get("send_success", False)))
        form.addRow("", self.send_success_check)
        return group

    def _build_smart_group(self) -> QtWidgets.QGroupBox:
        data = self._config.get("smart_options", {})
        group = QtWidgets.QGroupBox("SMART volby")
        layout = QtWidgets.QVBoxLayout(group)

        self.enable_short_check = QtWidgets.QCheckBox("Plánovat týdenní krátké testy")
        self.enable_short_check.setChecked(bool(data.get("enable_short", True)))
        layout.addWidget(self.enable_short_check)

        self.enable_long_check = QtWidgets.QCheckBox("Plánovat měsíční dlouhé testy")
        self.enable_long_check.setChecked(bool(data.get("enable_long", True)))
        layout.addWidget(self.enable_long_check)

        self.wait_check = QtWidgets.QCheckBox("Čekat na dokončení testů ( --wait )")
        self.wait_check.setChecked(bool(data.get("wait_for_completion", False)))
        layout.addWidget(self.wait_check)

        self.dry_run_check = QtWidgets.QCheckBox("Používat režim dry-run")
        self.dry_run_check.setChecked(bool(data.get("dry_run", False)))
        layout.addWidget(self.dry_run_check)
        return group

    def _build_schedule_group(self) -> QtWidgets.QGroupBox:
        schedule = self._config.get("schedule", {})
        group = QtWidgets.QGroupBox("Plánování")
        layout = QtWidgets.QGridLayout(group)
        layout.setColumnStretch(1, 1)

        self.schedule_widgets = {}

        def add_row(row: int, key: str, label: str, has_weekday: bool = False, extra: QtWidgets.QWidget | None = None) -> None:
            checkbox = QtWidgets.QCheckBox(label)
            checkbox.setChecked(bool(schedule.get(key, {}).get("enabled", False)))
            layout.addWidget(checkbox, row, 0)

            time_edit = QtWidgets.QTimeEdit()
            time_edit.setDisplayFormat("HH:mm")
            time_str = schedule.get(key, {}).get("time", "00:00")
            time = QtCore.QTime.fromString(time_str, "HH:mm")
            if not time.isValid():
                time = QtCore.QTime(0, 0)
            time_edit.setTime(time)
            layout.addWidget(time_edit, row, 1)

            weekday_combo = None
            if has_weekday:
                weekday_combo = QtWidgets.QComboBox()
                weekday_combo.addItems(config_module.WEEKDAYS)
                current = schedule.get(key, {}).get("weekday", config_module.WEEKDAYS[0])
                index = weekday_combo.findText(current)
                if index == -1:
                    index = 0
                weekday_combo.setCurrentIndex(index)
                layout.addWidget(weekday_combo, row, 2)
            elif extra is not None:
                layout.addWidget(extra, row, 2)

            self.schedule_widgets[key] = {
                "enabled": checkbox,
                "time": time_edit,
                "weekday": weekday_combo,
                "extra": extra,
            }

        add_row(0, "smart_daily", "Denní SMART", has_weekday=False)
        add_row(1, "raid_watch", "Denní RAID watch", has_weekday=False)
        add_row(2, "smart_short_weekly", "Týdenní krátký test", has_weekday=True)
        add_row(3, "smart_long_monthly", "Měsíční dlouhý test", has_weekday=True)

        raid_dry_run = QtWidgets.QCheckBox("Dry run")
        raid_dry_run.setChecked(bool(schedule.get("raid_check", {}).get("dry_run", False)))
        add_row(4, "raid_check", "Měsíční RAID kontrola", has_weekday=True, extra=raid_dry_run)

        return group

    def _build_manual_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Ruční spuštění")
        layout = QtWidgets.QHBoxLayout(group)

        self.manual_variant = QtWidgets.QComboBox()
        self.manual_variant.addItem("SMART denní", ("smart_daily.sh", []))
        self.manual_variant.addItem("SMART krátký", ("smart_daily.sh", ["--short"]))
        self.manual_variant.addItem("SMART dlouhý", ("smart_daily.sh", ["--long"]))
        self.manual_variant.addItem("RAID watch", ("raid_watch.sh", []))
        self.manual_variant.addItem("RAID check", ("raid_check.sh", []))
        self.manual_variant.addItem("Denní bundle", ("daily_checks.sh", []))
        layout.addWidget(self.manual_variant, stretch=1)

        self.run_button = QtWidgets.QPushButton("Spustit")
        self.run_button.clicked.connect(self.run_selected_script)
        layout.addWidget(self.run_button)

        return group

    # endregion

    def _with_browse(self, line_edit: QtWidgets.QLineEdit) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        button = QtWidgets.QPushButton("Procházet")
        button.clicked.connect(lambda: self._choose_directory(line_edit))
        layout.addWidget(button)
        return container

    def _choose_directory(self, line_edit: QtWidgets.QLineEdit) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Vyber složku", line_edit.text() or str(Path.home()))
        if directory:
            line_edit.setText(directory)

    def _collect_config(self) -> Dict[str, object]:
        config = dict(self._config)
        config["script_directory"] = self.script_dir_edit.text()
        config["log_settings"] = {
            "primary": self.primary_log_edit.text(),
            "fallback": self.fallback_log_edit.text(),
            "desktop_symlinks": self.desktop_symlink_check.isChecked(),
        }
        config["email"] = {
            "recipient": self.recipient_edit.text(),
            "subject_template": self.subject_edit.text(),
            "send_success": self.send_success_check.isChecked(),
        }
        config["smart_options"] = {
            "enable_short": self.enable_short_check.isChecked(),
            "enable_long": self.enable_long_check.isChecked(),
            "wait_for_completion": self.wait_check.isChecked(),
            "dry_run": self.dry_run_check.isChecked(),
        }

        schedule: Dict[str, object] = {}
        for key, widgets in self.schedule_widgets.items():
            entry = {
                "enabled": widgets["enabled"].isChecked(),
                "time": widgets["time"].time().toString("HH:mm"),
            }
            if widgets.get("weekday") is not None:
                entry["weekday"] = widgets["weekday"].currentText()
            if key == "raid_check":
                entry["dry_run"] = widgets["extra"].isChecked()
                entry["day_constraint"] = "first_week"
            if key == "smart_long_monthly":
                entry["day_constraint"] = "first_week"
            schedule[key] = entry
        config["schedule"] = schedule
        return config

    def update_cron_preview(self) -> None:
        preview_config = self._collect_config()
        entries = build_cron_entries(preview_config)
        self.cron_preview.setPlainText("\n".join(entries))

    def save_and_apply(self) -> None:
        config = self._collect_config()
        config_module.save_config(config)
        entries = build_cron_entries(config)
        try:
            result = apply_cron(entries)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Chyba", str(exc))
            return
        if result.returncode != 0:
            QtWidgets.QMessageBox.critical(
                self,
                "Chyba",
                f"Nepodařilo se zapsat crontab:\n{result.stderr or result.stdout}",
            )
            return
        self._config = config
        self.update_cron_preview()
        QtWidgets.QMessageBox.information(self, "Uloženo", "Konfigurace byla uložena a cron aktualizován.")

    def run_selected_script(self) -> None:
        script_dir = Path(self.script_dir_edit.text())
        script_name, base_flags = self.manual_variant.currentData()
        base_flags = list(base_flags)
        script_path = script_dir / script_name
        if not script_path.exists():
            QtWidgets.QMessageBox.critical(
                self,
                "Chyba",
                f"Skript {script_path} neexistuje. Zkontrolujte nastavení cesty.",
            )
            return

        smart_flags = []
        if script_name == "smart_daily.sh":
            if self.wait_check.isChecked():
                smart_flags.append("--wait")
            if self.dry_run_check.isChecked():
                smart_flags.append("--dry-run")
        if script_name == "raid_check.sh" and self.schedule_widgets["raid_check"]["extra"].isChecked():
            base_flags.append("--dry-run")

        command = [str(script_path), *base_flags, *smart_flags]
        self.output_box.appendPlainText(f"$ {' '.join(command)}")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, "Chyba", str(exc))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if result.stdout:
            self.output_box.appendPlainText(result.stdout)
        if result.stderr:
            self.output_box.appendPlainText(result.stderr)
        if result.returncode == 0:
            self.output_box.appendPlainText("✔️ Skript dokončen úspěšně")
        else:
            self.output_box.appendPlainText(f"❌ Skript skončil s chybou ({result.returncode})")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Diskové kontroly – správa")
        self.resize(900, 700)

        self._config = config_module.load_config()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(ServicesTab(self._config.get("services", [])), "Služby")
        tabs.addTab(DiskChecksTab(self._config), "Diskové kontroly")
        self.setCentralWidget(tabs)


def run() -> None:
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
