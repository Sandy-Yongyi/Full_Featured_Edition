"""UI-neutral access to operator-facing TOML configuration."""

from __future__ import annotations

from pathlib import Path

from model.utils.PasswordConfig import is_password_required
from model.utils.TomlLoader import TomlLoader


class ConfigurationService:
    def __init__(self, read_data_config_path: str | Path, mode_config_path: str | Path):
        self.read_data_config_path = str(read_data_config_path)
        self.mode_config_path = str(mode_config_path)

    def load_read_data(self) -> dict:
        return TomlLoader.load(self.read_data_config_path)

    def save_chain_speed(self, value: str | int) -> int:
        try:
            speed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("速度必须为1～50的整数，单位mm/s") from exc
        if not 1 <= speed <= 50:
            raise ValueError("速度必须为1～50的整数，单位mm/s")
        TomlLoader.save({"lidar_scan_speed": speed}, self.read_data_config_path)
        return speed

    def ensure_password_config(self) -> None:
        mode_config = TomlLoader.load(self.mode_config_path)
        if str(mode_config.get("auth_password", "") or "").strip():
            return
        TomlLoader.save({"auth_password": "123456"}, self.mode_config_path)

    def get_configured_password(self) -> str:
        mode_config = TomlLoader.load(self.mode_config_path)
        return str(mode_config.get("auth_password", "123456") or "123456")

    def is_password_required(self) -> bool:
        return is_password_required(self.mode_config_path)
