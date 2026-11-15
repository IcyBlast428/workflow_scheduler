"""Built-in administrator management of the independent Nacos bootstrap."""
from flask import Blueprint, request, g
from app.bootstrap import nacos_config, nacos_bindings
from app.bootstrap.global_vars import success_msg, error_msg
from app.api.platform_database import can_edit
from app.settings import AUTH_ADMIN_USERNAME
from app.common.nacos import Nacos, NacosError, NacosConflict, NacosPublishUncertain

blueprint = Blueprint('nacos_management', __name__)


@blueprint.get('/api/admin/nacos')
def settings():
    try:
        value = nacos_config.saved()
        return success_msg(dict(profile=nacos_config.public(value), can_edit=can_edit(),
                                editor_username=AUTH_ADMIN_USERNAME, configured=bool(value['url'])))
    except ValueError as exc:
        return error_msg(str(exc)), 400


@blueprint.post('/api/admin/nacos/<action>')
def change(action):
    # Deny before parsing any destination or making network requests. A generic
    # admin must not bypass the platform-DB boundary by modifying its Nacos file.
    if not can_edit():
        return error_msg('仅内置管理员账号可以读取、测试或修改 Nacos 配置。'), 403
    if action not in ('preview', 'test', 'save'):
        return error_msg('操作不存在。'), 404
    try:
        form = request.get_json(silent=True)
        if not isinstance(form, dict):
            raise ValueError('Nacos 配置必须为对象。')
        if action == 'preview':
            binding = nacos_bindings.validate(form.get('binding'))
            settings = nacos_config.saved()
            remote = nacos_bindings.read(binding, force_refresh=True, client=Nacos(config=settings))
            profile = {k: v for k, v in remote['values'].items() if k != 'password'}
            profile['password_set'] = bool(remote['values'].get('password'))
            return success_msg(dict(profile=profile, md5=remote['md5'], binding=binding, nacos_settings_token=nacos_config.version_token(settings)))
        profile = nacos_config.validate(form)
        if not profile['url']:
            raise ValueError('请填写 Nacos 服务地址。')
        result = Nacos(config=profile).test_connection(form.get('probe_binding'))
        if action == 'save':
            from app.bootstrap.operations import audit
            audit(g.identity['username'], 'nacos_connection_save', 'nacos', details='只读测试通过，保存 Nacos 连接设置。')
            result['profile'] = nacos_config.save(profile)
        return success_msg(result)
    except NacosConflict as exc:
        return error_msg(str(exc)), 409
    except (NacosPublishUncertain, NacosError) as exc:
        return error_msg(str(exc)), 503
    except ValueError as exc:
        return error_msg(str(exc)), 400
    except RuntimeError as exc:
        return error_msg(str(exc)), 409
    except OSError:
        return error_msg('Nacos 设置无法写入，请检查数据目录权限和磁盘空间。'), 503
