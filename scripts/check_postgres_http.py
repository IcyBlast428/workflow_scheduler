"""Check the running localhost PostgreSQL-backed app and safe demo outputs."""
import json
from pathlib import Path
import time
import requests

ROOT=Path(__file__).resolve().parents[1]


def main():
    password=next(line.split(': ',1)[1] for line in (ROOT/'data/local-login.txt').read_text(encoding='utf-8-sig').splitlines() if line.startswith('Password'))
    session=requests.Session()
    def call(method,path,**kwargs):
        response=session.request(method,'http://127.0.0.1:18008'+path,timeout=30,**kwargs)
        response.raise_for_status()
        result=response.json()
        assert result['code']==20000, result.get('message')
        return result['data']
    ready=call('GET','/api/user/ready')
    assert ready['ready']
    session.headers['X-CSRF-Token']=call('POST','/api/user/login',json={'username':'admin','password':password})['csrf_token']
    outputs=[]
    for pid,directory in [('pg_output_demo',''),('pg_nested_demo','reports')]:
        run=call('POST','/api/taskinfo/call_task',params={'pid':pid})['run_id']
        for _ in range(120):
            details=call('GET','/api/taskinfo/run',params={'run_id':run})
            record=details['record']
            if record['status'] not in ('queued','running'):
                assert record['status']=='success', record.get('reason')
                break
            time.sleep(.3)
        else: raise TimeoutError('Execution remained pending')
        listing=call('GET','/api/taskinfo/artifacts',params={'run_id':run,'dir':directory})
        assert len(listing['entries'])==3
        for item in listing['entries']:
            preview=call('GET','/api/taskinfo/artifacts',params={'run_id':run,'file':item['path']})
            assert preview['kind'] in ('csv','text')
            response=session.get('http://127.0.0.1:18008/api/taskinfo/artifact-download',params={'run_id':run,'file':item['path']},timeout=30)
            assert response.status_code==200 and len(response.content)>0
        outputs.append({'pid':pid,'run_id':run,'files':[item['path'] for item in listing['entries']]})
        print('HTTP_EXECUTION_AND_OUTPUTS_OK',pid,flush=True)
    dashboard=call('GET','/api/taskinfo/dashboard')
    assert dashboard['summary']['total']==2
    assert not list((ROOT/'data/gauss-dev/state').rglob('*.sqlite3'))
    (ROOT/'data/gauss-dev/http-acceptance.json').write_text(json.dumps(outputs,ensure_ascii=False,indent=2),encoding='utf-8')
    print('HTTP_POSTGRES_ACCEPTANCE_OK; two tasks; no SQLite state',flush=True)


if __name__=='__main__': main()
