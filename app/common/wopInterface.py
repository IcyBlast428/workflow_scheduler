import time
import json
import pprint
import hashlib
import requests
from app.settings import FLASK_ENV

class wopInterface_cls:
    # private variables
    # production keys
    __wop_execSingle_key = r"P_ExecSingle_Key"
    __wop_getExecResult_key = r"P_GetExecResult_Key"
    __wop_deployFile_key = r"P_DeployFile_Key"
    __wop_getFile_Key = r"P_GetFileDeployResult_Key"
    __wop_downloadFile_key = r"P_DownloadFile_Key"
    # wop server domain
    __wop_domain = r"dcap-esb.icbc"

    # for development env
    if FLASK_ENV == 'development':
        __wop_execSingle_key = r"V_ExecSingle_Key"
        __wop_getExecResult_key = r"V_GetExecResult_Key"
        __wop_deployFile_key = r"V_DeployFile_Key"
        __wop_getFile_Key = r"V_GetFile_Key"
        __wop_downloadFile_key = r"V_DownloadFile_Key"
        __wop_domain = r"76.13.45.205"

    def __init__(self, wop_userID, wop_userName, wop_mailList) -> None:
        self.__wop_userID = wop_userID
        self.__wop_userName = wop_userName
        self.__wop_mailList = wop_mailList

    def getKeys(self):
        print(self.__wop_execSingle_key)
        print(self.__wop_getExecResult_key)
        print(self.__wop_deployFile_key)
        print(self.__wop_getFile_Key)
        print(self.__wop_downloadFile_key)
    
    def execSingle(self, misName, misScope, scriptContent, execUser = "sysadmin"):
        # WOP_EXEC_SINGLE
        # appid
        appid = r"F-IMMP"
        # time stamp, int type is acceptable, no float
        timestamp = str(int(time.time()))
        # keys for validation environment
        execSingle_key = self.__wop_execSingle_key
        # exec single url
        execSingle_url = r"http://{domain}:8280/services/WOP_EXEC_SINGLE_SIGN".format(**{"domain": self.__wop_domain})
        # exec single string for doing sha256
        execSingle_sha256String = r"&dcap_timestamp={0}&key={1}".format(timestamp, execSingle_key)
        # sha256 sign
        execSingle_sha256Sign = hashlib.sha256(execSingle_sha256String.encode("utf-8")).hexdigest()
        # headers
        execSingle_headers = {
            'Content-Type': 'application/json',
            'dcap_timestamp': timestamp,
            'dcap_sign': execSingle_sha256Sign,
            'dcap_app_name': appid
        }
        # mission data for exec single
        execSingle_data_json = json.dumps(
        {
            'mission': {
                'app': 'F-IMMP',
                'userId': self.__wop_userID,
                'userName': self.__wop_userName, # optional
                'orgId': '0010100003',
                'mailList': self.__wop_mailList, # optional
                'misName': misName, # optional
                'misScope': misScope,
                'script': {
                    'type': 'sh',
                    'execUser': execUser, # optional
                    'timeOut': '600', # optional
                    'refMedias': '', # optional
                    'outputType': 'string', # optional
                    'content': scriptContent, # optional
                    'hasDangerCmd': 'false', #optional
                    'name': '', # optional
                    'path': '', # optional
                    'execParams': '' # optional
                }
            }
        })
        # post
        execSingle_response= requests.post(url = execSingle_url, headers = execSingle_headers, data = execSingle_data_json)
        # return result
        if (response_text := execSingle_response.text) == None:
            return "WOP get 'None' value returned."
        else:
            return json.loads(response_text)

    # WOP_GET_EXEC_RESULT
    # missionId = execSingle["mission"]["id"]
    def getExecResult(self, missionId):
        # appid
        appid = r"F-IMMP"
        # time stamp, int type is acceptable, no float
        timestamp = str(int(time.time()))
        # get exec result url
        getExecResult_url = r"http://{domain}:8280/services/WOP_GET_EXEC_RESULT_SIGN".format(**{"domain": self.__wop_domain})
        getExecResult_url = "?id=".join([getExecResult_url, missionId])
        # get exec result string for doing sha256
        getExecResult_sha256String = r"id={0}&dcap_timestamp={1}&key={2}".format(missionId, timestamp, self.__wop_getExecResult_key)
        # sha256 sign
        getExecResult_sha256Sign = hashlib.sha256(getExecResult_sha256String.encode("utf-8")).hexdigest()
        # get exec result header
        getExecResult_headers = {
            'Content-Type': 'application/json',
            'dcap_timestamp': timestamp,
            'dcap_sign': getExecResult_sha256Sign,
            'dcap_app_name': appid
        }
        # get exec result
        getExecResult_response = requests.get(url = getExecResult_url, headers = getExecResult_headers)
        # get result in dic format
        return json.loads(getExecResult_response.text)
    
    # deploy file
    def deployFile(self, misName, misScope, localFilePath, localFileName, remoteFilePath, remoteFileName):
        # appid
        appid = r"F-IMMP"
        # time stamp, int type is acceptable, no float
        timestamp = str(int(time.time()))
        # deploy file url
        deployFile_url = "http://{domain}:8280/services/WOP_DEPLOY_FILE_SIGN".format(**{"domain": self.__wop_domain})
        # deploy file string for doing sha256
        deployFile_sha256String = r"&dcap_timestamp={0}&key={1}".format(timestamp, self.__wop_deployFile_key)
        # sha256 sign
        deployFile_sha256Sign = hashlib.sha256(deployFile_sha256String.encode("utf-8")).hexdigest()
        # deploy file header
        deployFile_headers = {
            'dcap_timestamp': timestamp,
            'dcap_sign': deployFile_sha256Sign,
            'dcap_app_name': appid
        }
        # file data for deploy file
        deployFile_data_json = {
            'app': appid,
            'userId': self.__wop_userID,
            'userName': self.__wop_userName, # optional
            'orgId': '0010100003',
            'misName': misName, # optional
            'misScope': misScope, # one to many IPs
            'charset': 'UTF-8',
            'Content-Type': 'multipart/form-data',
            'fileName': remoteFileName, # may useless, fileName determined by 'file' dict down below
            'filePath': remoteFilePath
        }
        # overwrite the previous file when the file name is the same
        # and the dcap agent will generate {filename}.agent_bak{.num} for backing up the previous file
        # the default permission of the deployed file(s) is 744
        file = {
            'file': (remoteFileName, open(localFilePath + localFileName, "rb"), 'text/plain;UTF-8')
        }
        # deploy file
        deployFile_response = requests.post(
            url = deployFile_url,
            headers = deployFile_headers,
            data = deployFile_data_json,
            files = file
        )
        # .text: mission id; .status_code: status code
        return deployFile_response
    
    # WOP_GET_FILE_DEPLOY_RESULT_SIGN
    def getDeployResult(self, missionId):
        # appid
        appid = r"F-IMMP"
        # time stamp, int type is acceptable, no float
        timestamp = str(int(time.time()))
        # get deploy result url
        getDeployResult_url = r"http://{domain}:8280/services/WOP_GET_FILE_DEPLOY_RESULT_SIGN".format(**{"domain": self.__wop_domain})
        getDeployResult_url = "?missionid=".join([getDeployResult_url, missionId])
        # get deploy result string for doing sha256
        getDeployResult_sha256String = r"missionid={0}&dcap_timestamp={1}&key={2}".format(missionId, timestamp, self.__wop_getFile_Key)
        # sha256 sign
        getDeployResult_sha256Sign = hashlib.sha256(getDeployResult_sha256String.encode("utf-8")).hexdigest()
        # get deploy result header
        getDeployResult_headers = {
            'Content-Type': 'application/json',
            'dcap_timestamp': timestamp,
            'dcap_sign': getDeployResult_sha256Sign,
            'dcap_app_name': appid
        }
        # get deploy result
        getDeployResult_response = requests.get(url = getDeployResult_url, headers = getDeployResult_headers)
        # get deploy in dic format
        return json.loads(getDeployResult_response.text)
    
    def downloadFile(self, misName, misScope, remoteFilePath, remoteFileName, localFilePath, localFileName):
        # appid
        appid = r"F-IMMP"
        # time stamp, int type is acceptable, no float
        timestamp = str(int(time.time()))
        # deploy file url
        downloadFile_url = "http://{domain}:8280/services/WOP_DOWNLOAD_FILE".format(**{"domain": self.__wop_domain})
        # sha256 strings for each key
        downloadFile_sha256String = r"&dcap_timestamp={0}&key={1}".format(timestamp, self.__wop_downloadFile_key)
        # sha256 sign
        downloadFile_sha256Sign = hashlib.sha256(downloadFile_sha256String.encode("utf-8")).hexdigest()
        # headers
        # download file
        downloadFile_headers = {
            'Content-Type': 'application/json',
            'dcap_timestamp': timestamp,
            'dcap_sign': downloadFile_sha256Sign,
            'dcap_app_name': appid
        }
        downloadFile_data_json = json.dumps(
        {
            'mission': {
                'app': appid,
                'userId': self.__wop_userID,
                'userName': self.__wop_userName, # optional
                'orgId': '0010100003',
                'mailList': self.__wop_mailList, # optional
                'misName': misName, # optional
                'misScope': misScope, # just one ip, not support multiply IPs
                'file': {
                    'fileName': remoteFileName,
                    'filePath': remoteFilePath
                }
            }
        })
        # download file
        downloadFile_response = requests.post(
            url = downloadFile_url, 
            headers = downloadFile_headers, 
            data = downloadFile_data_json
        )
        with open(localFilePath + localFileName, 'w') as file_obj:
            file_obj.write(downloadFile_response.text)

# if __name__ == "__main__":
#     wop1 = wopInterface_cls(wop_userID = r"001226522", wop_userName = r"yu.cong", wop_mailList = r"yu.cong@dc.icbc.com.cn")
    
#     # execute single command
#     wop1_execSingle = wop1.execSingle(
#         misName = r"exec single wop interface test", 
#         misScope = r"84.122.98.44", 
#         scriptContent = r'''
#         cat /etc/SuSE-release
#         cat /etc/os-release
#         '''
#     )
#     pprint.pprint(wop1_execSingle["mission"]["misResult"])
#     # get execution result
#     wop1.getExecResult(missionId = wop1_execSingle["mission"]["id"])
    
#     # deploy file
#     wop1_deployFile = wop1.deployFile(
#         misName = r"deploy file wop interface test", 
#         misScope = r"84.122.98.44", 
#         localFilePath = r"C:\\Users\\dccs-congy\\Desktop\\",
#         localFileName = r"vm_check_v1.sh",
#         remoteFilePath = r"/tempfile/",
#         remoteFileName = r"vm_check_v1.sh"
#     )

#     # get deploy result
#     pprint.pprint(wop1.getDeployResult(wop1_deployFile["missionId"]))

#     # download file
#     wop1.downloadFile(
#         misName=r"download file wop interface test",
#         misScope=r"84.122.98.44",
#         remoteFilePath=r"/tempfile/",
#         remoteFileName=r"system.info",
#         localFilePath=r"C:\\Users\\dccs-congy\\Desktop\\",
#         localFileName=r"system.info"
#     )