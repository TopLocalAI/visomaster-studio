"""Locate bundled tools and keep writable caches outside the signed app."""
import os
from pathlib import Path
import sys


def configure_runtime():
    source = Path(__file__).resolve().parents[2]
    resources = source.parent
    python = resources / 'python/bin/python3.12'
    if not python.is_file():
        return
    sys.dont_write_bytecode = True
    sys.executable = str(python)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['PYTHONNOUSERSITE'] = '1'
    os.environ.pop('PYTHONPATH', None)
    os.environ['PATH'] = str(resources / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin'
    from .config import data_root
    cache = data_root() / 'runtime'
    cache.mkdir(parents=True, exist_ok=True)
    for key, folder in [('TORCH_HOME', 'torch'), ('HF_HOME', 'huggingface'), ('XDG_CACHE_HOME', 'cache')]:
        os.environ[key] = str(cache / folder)
    os.chdir(cache)
