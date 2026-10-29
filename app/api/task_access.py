"""Account grants and capability annotations, isolated from task list queries."""
from flask import Blueprint,request,g
from app.bootstrap.global_vars import success_msg,error_msg
from app.bootstrap import task_access

blueprint=Blueprint('task_access',__name__)

@blueprint.route('/api/admin/task-access',methods=['GET','POST'])
def access():
    username=request.args.get('username','')
    if not username or len(username)>100:return error_msg('请选择账户。'),400
    try:
        if request.method=='POST':
            value=task_access.save(username,request.get_json(silent=True) or {},g.identity['username'])
            from app.bootstrap.operations import audit
            audit(g.identity['username'],'task_access',username,details=str(value))
            g.audit_forwarded=True
        return success_msg(task_access.configuration(username))
    except ValueError as exc:return error_msg(str(exc)),400
    except RuntimeError as exc:return error_msg(str(exc)),409

@blueprint.after_app_request
def capabilities(response):
    if request.path!='/api/taskinfo/state' or not getattr(g,'identity',None) or not response.is_json:return response
    payload=response.get_json();data=payload.get('data') or {}
    if isinstance(data,dict):
        for item in data.get('items',[]):
            item['permissions']=task_access.for_task(g.identity,item['id'],item.get('group_name'))
        response.set_data(__import__('json').dumps(payload,ensure_ascii=False))
    return response
