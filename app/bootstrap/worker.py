"""Small stdlib-only entry point for task environments, without importing Flask."""
import argparse
import os
import runpy
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--memory-mb', type=int, default=0)
parser.add_argument('--cpu-seconds', type=int, default=0)
parser.add_argument('--file-mb', type=int, default=0)
parser.add_argument('--task-root', default='')
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
root = Path(args.task_root or Path(args.entry).parent).resolve()
entry = Path(args.entry).resolve()
relative = entry.relative_to(root)
package_root = entry.parent
while package_root != root and (package_root / '__init__.py').is_file() and package_root.name.isidentifier():
    package_root = package_root.parent
search_roots = [root, package_root, entry.parent]
if (root / 'src').is_dir():
    search_roots.insert(1, root / 'src')
sys.path[:0] = list(dict.fromkeys(str(path) for path in search_roots))
sys.argv = [args.entry]
# Include conventional src/ layouts while preserving the task's package-root cwd.
module_parts = entry.relative_to(package_root).with_suffix('').parts
package_entry = len(module_parts) > 1 and all(part.isidentifier() for part in module_parts)
if package_entry:
    runpy.run_module('.'.join(module_parts), run_name='__main__', alter_sys=True)
else:
    runpy.run_path(args.entry, run_name='__main__')
