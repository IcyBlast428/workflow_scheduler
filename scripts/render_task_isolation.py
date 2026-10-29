"""Render a production Scheduler drop-in. Does not change services or permissions."""
import argparse
from pathlib import Path
import pwd

def render(user):
    uid=pwd.getpwnam(user).pw_uid
    return f"""[Unit]
Wants=user@{uid}.service
After=user@{uid}.service

[Service]
Environment=XDG_RUNTIME_DIR=/run/user/{uid}
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus
"""

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--user',default='wfs');parser.add_argument('--output',required=True)
    args=parser.parse_args()
    with open(args.output,'x') as output:output.write(render(args.user))
    print(args.output)
