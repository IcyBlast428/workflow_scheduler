import json,os,sys,tempfile,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from app.bootstrap.shared_sdk import freeze
from app.bootstrap.task_isolation import wrapper
with tempfile.TemporaryDirectory(prefix='wfs-isolation-') as temporary:
 base=Path(temporary); code=base/'release/code';code.mkdir(parents=True)
 freeze(base/'release')
 data=base/'data';data.mkdir();output=data/'out';output.mkdir();(data/'other-secret').write_text('must stay hidden')
 os.environ['WFS_DATA_DIR']=str(data)
 source=code/'main.py'
 source.write_text('''import os
from pathlib import Path
assert not Path(os.environ['WFS_DATA_DIR'],'other-secret').exists()
assert not Path.home().joinpath('.ssh').exists()
assert 'WFS_SECRET_KEY' not in os.environ
assert len([p for p in Path('/proc').iterdir() if p.name.isdigit()])<20
Path(os.environ['WFS_OUTPUT_DIR'],'probe.txt').write_text('isolated')
try:
    Path(__file__).write_text('bad')
except OSError: pass
else: raise AssertionError('code writable')
print('ISOLATION_OK')
''')
 env={'PATH':os.environ['PATH'],'WFS_DATA_DIR':str(data),'WFS_OUTPUT_DIR':str(output),'WFS_TASK_CONNECTIONS_JSON':'{}','PYTHONDONTWRITEBYTECODE':'1'}
 command=[sys.executable,'-u',str(root/'app/bootstrap/worker.py'),'--task-root',str(code),str(source)]
 args,environment,unit=wrapper(command,env,code,base/'release/shared-sdk',output,output,'a'*32,{})
 result=subprocess.run(args,env=environment,capture_output=True,timeout=30,text=True)
 print('returncode',result.returncode)
 print(result.stdout[-1000:]);print(result.stderr[-1500:])
 assert result.returncode==0
 assert (output/'probe.txt').read_text()=='isolated'
