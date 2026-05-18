import re
import http
import base64
import urllib
import logging
import pandas as pd
from app.common.database import NewDB
from app.common.nacos import Nacos

def send_sms(phone_list, msg_body):
    if len(phone_list) == 0 or len(msg_body) == 0:
        return
    try:
        headers = {"Content-type": "application/x-www-form-urlencoded", "charset": "GBK", "Accept": "*/*"}
        phone_list = ';'.join(phone_list)
        msg_body = "【IMMP-WFS】" + msg_body
        request_body = f'''
        <?xml version="1.0" encoding="GBK"?>
        <request>
            <cmdid>1</cmdid>
            <head>
                <user>POSTMAN</user>
                <pwd>UMS</pwd>
                <busstype>001</busstype>
                <tempno>NONE</tempno>
                <sendmode>1</sendmode>
                <policyno>PIPGW001</policyno>
                <clienttrace>{{clienttrace}}</clienttrace>
                <prioritylevel>1</prioritylevel>
                <addressinfo>
                    <address>
                        <attribute>
                            <key>phone</key>
                            <value>{phone_list}</value>
                        </attribute>
                        <attribute>
                            <key>needreport</key>
                            <value>N</value>
                        </attribute>
                        <attribute>
                            <key>isLongSMS</key>
                            <value>Y</value>
                        </attribute>
                        <attribute>
                            <key>contenttype</key>
                            <value>15</value>
                        </attribute>
                    </address>
                </addressinfo>
            </head>
            <body><![CDATA[{msg_body}]]></body>
        </request>
        '''
        data = urllib.parse.urlencode({
            "LoginUser": "POSTMAN",
            "LoginPwd": base64.b64decode(b'VU1T').decode("utf-8"),
            "cmdID": 1,
            "Content": request_body.encode("GBK")
        })
        host = "umsp-app-it-no.icbc"
        http_client = http.client.HTTPConnection(host, 9080)
        url = "/umsWeb/send"
        http_client.request('POST', url, data, headers)
    except Exception as e:
        logging.getLogger(__name__).warning(e)

'''
nacos配置：
namespace：wfs
dataID：作业名.json，如ping_monitor.json，注意一定要加上.json后缀
group：作业对应分组，如ping_monitor对应healthCheck组

方法调用：返回结果示例为["138xxxx1234", "139xxxx1234", "140xxxx1234"]，可直接赋值send_sms方法phone_list参数
一：不加参数默认返回系统一部所有联系人
receivers_list = get_sms_list()
二：参数
job_group：作业分组
job_name：作业名
injob_part：同一任务内分别发送不同联系人或群组，part1可自定义名称(nacos中名称需和调用时名称相同)
            即使任务中只发送同一联系人或群组，也许定义名称
receivers_list = get_sms_list(job_name = "ping_monitor", job_group = "healthCheck", injob_part = "part1")

依据 mysql_immpdb.immp_cfg_user_mail_sms 表
单独联系人写进sms_receivers_individual键值内{id:姓名}
整组联系人写进sms_receivers_group键值内{部门:组名}
其中部门以表内department字段为基础
组名分两类：
一类以mygroup字段内容为基础，值为字段值
另一类已is_xxxx字段名为基础，值为xxxx字段名后缀
举例说明一：取系统一部所有联系人
{
	"part1": {
		"sms_receivers_group": [{ "系统一部": "all" }]
	}
}
举例说明二：取系统一部所有联系人并加上外部门两人
{
	"base": {
		"sms_receivers_individual": [
			{ "001***487": "吴*雄" },
			{ "001***417": "王*明" }
		],
		"sms_receivers_group": [{ "系统一部": "all" }]
	}
}
举例说明三：取系统一部自动化组所有人
{
	"base": {
		"sms_receivers_group": [{ "系统一部": "sa" }]
	}
}
举例说明四：取系统一部所有经理三，并加上自动化组所有人
{
	"base": {
		"sms_receivers_group": [
			{ "系统一部": "sa" },
			{ "系统一部": "manager3" }
		]
	}
}
举例说明五：任务中不同地方发送不同联系人，part_all部分发送系统一部全体并加上外部门两人，part_sa发送自动化组所有人
{
	"part_all": {
		"sms_receivers_individual": [
			{ "001***487": "吴*雄" },
			{ "001***417": "王*明" }
		],
		"sms_receivers_group": [{ "系统一部": "all" }]
	},
	"part_sa": {
		"sms_receivers_group": [{ "系统一部": "sa" }]
	}
}
无需担心重复取值，会过滤重复号码
所有组配置："all"，"sa"，"db"，"cics"，"os"，"jg"，"ld"，"kjzf"，"jhzf"，"manager3"
'''
def get_sms_list(job_group = "default", job_name = "default", injob_part = "default"):
    # 联系人属于业务库数据，通过 common.db.NewDB 走非高斯数据库连接。
    with NewDB("mysql_immpdb") as immpdb_obj:
        immpdb_connection = immpdb_obj.get_connection()

        # return all phone number of people in 系统一部
        if job_name == "default" and job_group == "default":
            sms_receivers_query_sql = "select telephone from immp_cfg_user_mail_sms where department = '系统一部'"
            sms_receivers_phone_df = pd.read_sql(sms_receivers_query_sql, con = immpdb_connection)
            return sms_receivers_phone_df["telephone"].tolist()

        # get raw data from nacos
        receivers_dic = Nacos().get_nacos_configs(tenant= 'wfs', data_id= job_name + '.json', group= job_group)
        # split partion
        receivers_dic = receivers_dic[injob_part]
        # split sms and mail receivers
        sms_receivers_dic = {}
        for receivers_dic_key in receivers_dic.keys():
            if re.search(r"^sms.*", receivers_dic_key) != None:
                sms_receivers_dic[receivers_dic_key] = receivers_dic[receivers_dic_key]
        # split individual and group receivers
        sms_receivers_individual_list = []
        sms_receivers_group_list = []
        for sms_receivers_dic_key in sms_receivers_dic.keys():
            if re.search(r".*?individual$", sms_receivers_dic_key) != None:
                sms_receivers_individual_list = sms_receivers_dic[sms_receivers_dic_key]
            if re.search(r".*?group$", sms_receivers_dic_key) != None:
                sms_receivers_group_list = sms_receivers_dic[sms_receivers_dic_key]

        # for individual
        sms_receivers_individual_phone_list = []
        if len(sms_receivers_individual_list) != 0:
            sms_receivers_individual_aamid_list = [aamid for person_dic in sms_receivers_individual_list for aamid in person_dic.keys()]
            sms_receivers_individual_aamid_query_clause_str = '\'' + "','".join(sms_receivers_individual_aamid_list) + '\''
            sms_receivers_individual_aamid_query_sql = f"select telephone from immp_cfg_user_mail_sms where aamid in ({sms_receivers_individual_aamid_query_clause_str})"
            sms_receivers_individual_phone_df = pd.read_sql(sms_receivers_individual_aamid_query_sql, con = immpdb_connection)
            sms_receivers_individual_phone_list = sms_receivers_individual_phone_df["telephone"].tolist()

        # for group
        sms_receivers_group_phone_list = []
        if len(sms_receivers_group_list) != 0:
            for group_dic in sms_receivers_group_list:
                for depart, group in group_dic.items(): # one time
                    if group == "all":
                        sms_receivers_group_query_sql = f"select telephone from immp_cfg_user_mail_sms where department = '{depart}'"
                    if group in ("sa", "os", "db", "cics", "jg", "ld"):
                        sms_receivers_group_query_sql = f"select telephone from immp_cfg_user_mail_sms where mygroup in ('{group}')"
                    if group in ("kjzf", "jhzf", "manager3"):
                        sms_receivers_group_query_sql = f"select telephone from immp_cfg_user_mail_sms where is_{group} = 1"
                    sms_receivers_group_phone_df = pd.read_sql(sms_receivers_group_query_sql, con = immpdb_connection)
                    sms_receivers_group_phone_list.extend(sms_receivers_group_phone_df["telephone"].tolist())

        # combine individual and group receivers
        sms_receivers_phone_list = sms_receivers_individual_phone_list + sms_receivers_group_phone_list
        # remove duplicates
        sms_receivers_phone_list = list(set(sms_receivers_phone_list))
        return sms_receivers_phone_list
