import re
import json
import requests
import os

class Nacos:
    def __init__(self) -> None:
        self.__nacos_url = os.environ.get('WFS_NACOS_URL', '')
        self.__nacos_token_api = "/v1/auth/login"
        self.__nacos_config_api = "/v1/cs/configs"
        self.__nacos_login_un = os.environ.get('WFS_NACOS_USERNAME', '')
        self.__nacos_login_pd = os.environ.get('WFS_NACOS_PASSWORD', '')

    # 获取nacos token
    def __get_nacos_token(self):
        if not all((self.__nacos_url, self.__nacos_login_un, self.__nacos_login_pd)):
            raise RuntimeError('Nacos credentials are not configured')
        nacos_get_token_url = self.__nacos_url + self.__nacos_token_api
        body = {
            "username": self.__nacos_login_un,
            "password": self.__nacos_login_pd
        }
        response = requests.post(url=nacos_get_token_url, data=body, timeout=10)
        response.raise_for_status()
        return response.json()['accessToken']

    # 获取nacos配置
    def get_nacos_configs(self, tenant = '', data_id = '', group = ''):
        nacos_token = self.__get_nacos_token()
        nacos_get_config_url = self.__nacos_url + self.__nacos_config_api
        params = {
            "tenant": tenant,
            "dataId": data_id,
            "group": group
        }
        headers = {"Authorization": f"Bearer {nacos_token}"}
        response = requests.get(nacos_get_config_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        conf_text = response.text
        if (conf_format := re.search(r"[^\.]*$", data_id).group(0)) == "json":
            conf = json.loads(conf_text)
        elif conf_format == "text":
            conf = conf_text
        return conf
