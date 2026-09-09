#!/usr/bin/env python3
"""Collect public BTC/ETH perpetual data into a new Git-external capture root."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lab.perp_data import main
if __name__=='__main__': main()
