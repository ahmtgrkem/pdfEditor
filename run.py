"""Geliştirme başlatıcısı:  python run.py [dosya.pdf]"""
from __future__ import annotations

import sys

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
