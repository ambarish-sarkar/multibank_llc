#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from Normal_cache_occupancy.simulator import Simulator as _Base


class Simulator(_Base):
    DESIGN = "mirage"
