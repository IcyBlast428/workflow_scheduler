import re
import json
import requests

class Nacos:
    def __init__(self) -> None:
        self.__nacos_url = "http://nacos.immp.icbc/nacos"
        self.__nacos_token_api = "/v1/auth/login"
        self.__nacos_config_api = "/v1/cs/configs"
        self.__nacos_login_un = "immp"
        self.__nacos_login_pd = "aW1tcA=="

    # 获取nacos token
    def __get_nacos_token(self):
        nacos_get_token_url = self.__nacos_url + self.__nacos_token_api
        body = {
            "username": self.__nacos_login_un,
            "password": self.__nacos_login_pd
        }
        response = requests.post(url = nacos_get_token_url, data = body)
        try:
            token = json.loads(response.text)["accessToken"]
        except:
            token = ''
        return token

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
        conf_text = requests.get(nacos_get_config_url, params = params, headers = headers).text
        if (conf_format := re.search(r"[^\.]*$", data_id).group(0)) == "json":
            conf = json.loads(conf_text)
        elif conf_format == "text":
            conf = conf_text
        return conf
