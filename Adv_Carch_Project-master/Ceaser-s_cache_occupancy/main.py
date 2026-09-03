#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from common import parse_config
from common_driver import run_design_experiment


if __name__ == "__main__":
    run_design_experiment("ceaser_s", parse_config())
