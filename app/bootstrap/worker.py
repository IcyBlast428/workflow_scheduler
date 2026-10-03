"""Small stdlib-only entry point for task environments, without importing Flask."""
import argparse
import os
import runpy
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--memory-mb', type=int, default=0)
parser.add_argument('--cpu-seconds', type=int, default=0)
parser.add_argument('--file-mb', type=int, default=0)
parser.add_argument('entry')
args = parser.parse_args()
if os.name != 'nt':
    import resource
    for value, limit, multiplier in (
        (args.memory_mb, resource.RLIMIT_AS, 1024 * 1024),
        (args.cpu_seconds, resource.RLIMIT_CPU, 1),
        (args.file_mb, resource.RLIMIT_FSIZE, 1024 * 1024),
    ):
        if value:
            resource.setrlimit(limit, (value * multiplier, value * multiplier))
sys.path.insert(0, os.path.dirname(os.path.abspath(args.entry)))
sys.argv = [args.entry]
runpy.run_path(args.entry, run_name='__main__')
