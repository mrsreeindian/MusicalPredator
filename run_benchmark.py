"""
Entry point for running the Predator Keyboard Music Sync benchmark suite.
Executes multiple passes to verify performance, latency, and correctness.
"""

import sys
from predator_music_sync.benchmark.benchmark_suite import run_comprehensive_benchmark

if __name__ == "__main__":
    passes = 3
    if len(sys.argv) > 1:
        try:
            passes = int(sys.argv[1])
        except ValueError:
            pass
    run_comprehensive_benchmark(passes=passes)
