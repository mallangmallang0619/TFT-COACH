"""Separate installed resources from writable user data; preserve source paths."""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import sys


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    data: Path
    logs: Path
    diagnostics: Path
    training: Path
    frozen: bool


def resolve_paths(frozen, executable, environ):
    source = Path(__file__).resolve().parent.parent
    if not frozen:
        return AppPaths(source, source / 'assets', source / 'backend/_logs',
                        source / 'backend/_debug', source / 'backend/_training', False)
    resources = Path(executable).resolve().parent.parent
    default = Path(environ.get('LOCALAPPDATA', Path.home())) / 'TFT Coach'
    data = Path(environ.get('TFT_COACH_USER_DATA') or default)
    return AppPaths(resources, data, data / 'logs', data / 'diagnostics', data / 'training', True)


PATHS = resolve_paths(getattr(sys, 'frozen', False), sys.executable, os.environ)


def cache_path(name):
    destination = PATHS.data / name
    if PATHS.frozen:
        destination.parent.mkdir(parents=True, exist_ok=True)
        seed = PATHS.resources / 'assets' / name
        if not destination.exists() and seed.exists():
            # Exclusive creation avoids overwriting a concurrent refresh.
            try:
                with destination.open('xb') as output, seed.open('rb') as source:
                    shutil.copyfileobj(source, output)
            except FileExistsError:
                pass
    return destination
