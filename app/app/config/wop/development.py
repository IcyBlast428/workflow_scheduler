WOP_CFG_DICT = {
    'userId': "000786773",  # 统一使用有权限用户id去执行wop接口
    'userName': "dccs-cxzhang",
    'app': "F-IMMP",
    'orgId': "0010100003",
    'mailList': "",
    'misName': "immp mission",
    'type': "sh",
    'refMedias': [],
    'timeOut': 60000,
    'outputType': "string",
    'exec_url': 'http://76.10.237.27:9001/api/scriptApi/execSingle',
    'query_url': 'http://76.10.237.27:9001/api/scriptApi/mission?',
    'hasDangerCmd': 'true',
    'headers': {
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    },
    'script_types': ['sh', 'bat', 'pl', 'py', 'vbs'],
    'default_script_type': 'sh'
}

