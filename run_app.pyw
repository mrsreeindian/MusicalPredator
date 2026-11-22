"""
Predator Keyboard Music Sync - Windowless Application Entry Point
Can be double-clicked or executed with pythonw.exe with zero command console window.
"""

import sys
import os

# Ensure package directory is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from predator_music_sync.main import main

if __name__ == "__main__":
    main()
