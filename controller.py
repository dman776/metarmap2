#!/usr/bin/python3
"""
Starts the map, like `python -m metarmap`.

Maps installed with an older metarmap.service start this file, and so does their restart after an update,
so it stays here. New installs run `python3 -m metarmap` (see metarmap.service), and the map switches an older
installed service file over when it starts (metarmap/service.py).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from metarmap.app import main  # noqa: E402

main()
