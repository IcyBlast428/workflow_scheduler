"""Build a credential-free task SDK wheel for a private PyPI repository."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def build(version,output):
    from packaging.version import Version
    from app.bootstrap.shared_sdk import freeze
    version=str(Version(version))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    name='workflow_scheduler_task_sdk'
    filename=output/f'{name}-{version}-py3-none-any.whl'
    records=[]
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);digest=freeze(root)
        files={p.relative_to(root/'shared-sdk').as_posix():p.read_bytes() for p in (root/'shared-sdk/app').rglob('*.py')}
        metadata=f'{name}-{version}.dist-info'
        files[metadata+'/METADATA']=('Metadata-Version: 2.1\nName: workflow-scheduler-task-sdk\nVersion: '+version+'\nRequires-Python: >=3.12\nRequires-Dist: configobj==5.0.8\nRequires-Dist: SQLAlchemy==2.0.46\nRequires-Dist: PyMySQL==1.1.0\nRequires-Dist: requests==2.32.5\nRequires-Dist: cryptography==50.0.2\nRequires-Dist: pyDes==2.0.1\n\nFrozen task SDK '+digest+'\n').encode()
        files[metadata+'/WHEEL']=b'Wheel-Version: 1.0\nGenerator: wfs-sdk-builder\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
        files[metadata+'/wfs-sdk.json']=json.dumps({'shared_sdk_sha256':digest,'scope':'task environments only'}).encode()
        for key,data in sorted(files.items()):
            records.append((key,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('='),len(data)))
        records.append((metadata+'/RECORD','',''))
        stream=io.StringIO();csv.writer(stream,lineterminator='\n').writerows(records);files[metadata+'/RECORD']=stream.getvalue().encode()
        with zipfile.ZipFile(filename,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for key,data in sorted(files.items()):
                info=zipfile.ZipInfo(key,date_time=(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
                archive.writestr(info,data)
    return filename

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(build(args.version,args.output))
