"""Resolve deployment paths before importing configuration or file loggers."""

import os
import sys
from pathlib import Path


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def prepare_environment() -> Path:
    root = application_directory()
    os.chdir(root)
    return root
