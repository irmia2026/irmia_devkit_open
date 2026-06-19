"""config — 全局配置单例。"""
from __future__ import annotations

import os
from pathlib import Path

_plugin_dir: Path | None = None
_config: dict = {}


def set_config(cfg: dict, plugin_dir: str = "") -> None:
    global _config, _plugin_dir
    _config = cfg
    if plugin_dir:
        _plugin_dir = Path(plugin_dir)
    # 保证默认值
    try:
        default_backup_dir = str(Path.home() / ".irmia" / "backups")
    except RuntimeError:
        default_backup_dir = str(Path(plugin_dir) / ".irmia" / "backups") if plugin_dir else str(Path.cwd() / ".irmia" / "backups")
    _config.setdefault("backup_dir", default_backup_dir)
    _config.setdefault("gh_path", "")
    _config.setdefault("es_path", "")
    _config.setdefault("op_log_db", "")


def get_config() -> dict:
    """获取当前配置 dict。各工具模块调用此函数读取配置。"""
    return _config


def get_plugin_dir() -> Path | None:
    """获取插件根目录路径。"""
    return _plugin_dir


def get_owner_sid() -> str:
    """获取主人会话 ID。空字符串表示未配置。"""
    return _config.get("owner_sid", "")
