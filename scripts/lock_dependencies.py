"""Freeze only the installed dependency closure, excluding unrelated old packages."""
from importlib.metadata import distribution
from pathlib import Path
try:
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
pending = [Requirement(line) for line in (ROOT/'requirements.txt').read_text().splitlines() if line and not line.startswith('#')]
locked = {}
while pending:
    requirement = pending.pop()
    if requirement.marker and not requirement.marker.evaluate({'extra':''}):
        continue
    name = canonicalize_name(requirement.name)
    if name in locked:
        continue
    package = distribution(requirement.name)
    locked[name] = package.version
    pending.extend(Requirement(value) for value in package.requires or [])
path = ROOT/'requirements-linux-py312.lock'
path.write_text('# Validated on Linux x86_64 / CPython 3.12. Regenerate after dependency changes.\n' + ''.join(f'{name}=={version}\n' for name,version in sorted(locked.items())))
print(f'Locked {len(locked)} packages')
