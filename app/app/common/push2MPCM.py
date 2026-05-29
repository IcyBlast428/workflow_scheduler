# import pymysql
import requests
import datetime
# import base64
from app.common.database import NewDB
from app.settings import FLASK_ENV, MPCM_ACCESS_TOKEN
from urllib.parse import quote_plus


def mpcm_push(team, mail_title, mail_text='', file_name='', file_path='', alert=0):
    """
    :param team: (str)需关注专业组，多个英文逗号分隔，eg:'ZOS,DB2,CICS,SA'
    :param mail_title: (str)邮件标题，不需带日期，eg:'平台服务器日巡检情况(CPU使用率)'
    :param mail_text: (str)邮件正文，写入数据的html文本，文本中不能带有英文单引号，默认''
    :param alert: (int)邮件中异常条数，多个表格则将需要关注的行数相加，默认0，eg:10
    :param file_name: (str)附件名，默认''
    :param file_path: (str)本地附件路径+附件名，默认''
    :return None
    """
    date_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    mails_push_sql = """
    insert into zb_mails_push(datetime, team, mail_title, mail_text, mail_attachment, alert, handle)
    values (%(datetime)s, %(team)s, %(mail_title)s, %(mail_text)s, %(mail_attachment)s, %(alert)s, %(handle)s)
    """
    if FLASK_ENV == 'development':
        file_dir = r'C:/data/vols/mpcm_immp/mails/receive_files/'
    else:
        file_dir = r'/data/vols/mpcm_immp/mails/receive_files/'

    def mail_attachment(file_name):
        if file_name == '':
            return ''
        return ''.join([file_dir, datetime.datetime.now().strftime('%Y%m%d'), '/', file_name])

    def handle(alert):
        return 0 if alert == 0 else 1

    # MPCM 推送依赖业务库 mysql_xnrl，保持在 common 非高斯连接工厂中管理。
    with NewDB('mysql_xnrl') as db:
        db.insert_many(mails_push_sql, args={
            'datetime': date_time,
            'team': team.upper(),
            'mail_title': mail_title,
            'mail_text': mail_text,
            'mail_attachment': mail_attachment(file_name),
            'alert': alert,
            'handle': handle(alert),
        })

    if file_name != '' and file_path != '':
        if FLASK_ENV == 'development':
            url = "http://127.0.0.1:8000/mails/receive_files/"
        else:
            url = "http://mpcm.icbc/mails/receive_files/"
        headers = {
            "Content-Disposition": "attachment; filename={0}".format(quote_plus(file_name)),
            "Authentication": MPCM_ACCESS_TOKEN,
        }
        with open(file_path, 'rb') as file_data:
            requests.post(url, data=file_data, headers=headers)
