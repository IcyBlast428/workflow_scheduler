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
    :param alert: (int)邮件中异常条数，多个表格则将需要关注的行数相加，附件则为附件中需要关注的行数，默认0，eg:10
    :param file_name: (str)附件名，默认''，eg:'saes_table.xls'
    :param file_path: (str)本地附件路径+附件名，默认''，eg:'D:\Services\MysqlMonitor\saes_table.xls' 

    :return None
    """ 

    date_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # mail_text = ''
    # alert = 0
    # file_name = ''
    # file_path = ''
    # if 'mail_text' in kwargs.keys():
    #     mail_text = kwargs['mail_text']
    # if 'alert' in kwargs.keys():
    #     alert = kwargs['alert']
    # if 'file_name' in kwargs.keys():
    #     file_name = kwargs['file_name']
    # if 'file_path' in kwargs.keys():
    #     file_path = kwargs['file_path']

    # tidbparams = {'host'    : 'Lab-tidb.icbc', 'port': 4000, 'user': 'alg',
    #               'password': base64.b64decode('YWxn').decode('utf-8'), 'db': 'xnrldb',
    #               'charset' : 'utf8'}

    # mails_push_sql = '''insert into zb_mails_push(datetime,team,mail_title,mail_text,mail_attachment,alert,handle)
    #                     values ('{datetime}','{team}','{mail_title}','{mail_text}','{mail_attachment}',{alert},{handle})'''
    mails_push_sql = """
    insert into zb_mails_push(datetime,    team,    mail_title,    mail_text,   mail_attachment,     alert,    handle) 
                    values (%(datetime)s,%(team)s,%(mail_title)s,%(mail_text)s,%(mail_attachment)s,%(alert)s,%(handle)s)
    """
    if FLASK_ENV == 'development':
        file_dir = r'C:/data/vols/mpcm_immp/mails/receive_files/'
    else:
        file_dir = r'/data/vols/mpcm_immp/mails/receive_files/'
    mail_attachment = lambda file_name: ''.join([file_dir, datetime.datetime.now().strftime('%Y%m%d'), '/', file_name]) if file_name != '' else ''

    handle = lambda alert: 0 if alert == 0 else 1 

    # mails_push_sql = mails_push_sql.format(datetime=date_time, team=team.upper(), mail_title=mail_title,
    #                                         mail_text=mail_text,
    #                                         mail_attachment=mail_attachment(file_name),
    #                                         alert=alert,
    #                                         handle=handle(alert))
    db = NewDB('mysql_xnrl')
    db.get_engine()
    db.insert_many(mails_push_sql, args={'datetime'       : date_time,
                                         'team'           : team.upper(),
                                         'mail_title'     : mail_title,
                                         'mail_text'      : mail_text,
                                         'mail_attachment': mail_attachment(file_name),
                                         'alert'          : alert,
                                         'handle'         : handle(alert)
                                         })

    # tidbconn = pymysql.connect(**tidbparams)
    # with tidbconn.cursor() as tidbcursor:
    #     tidbcursor.execute(mails_push_sql)
    #     tidbconn.commit()
    # tidbconn.close()

    if (file_name != '' and file_path != ''):
        if FLASK_ENV == 'development':
            url = "http://127.0.0.1:8000/mails/receive_files/"
        else:
            url = "http://mpcm.icbc/mails/receive_files/"
        headers = {
                "Content-Disposition": "attachment; filename={0}".format(quote_plus(file_name)),
                "Authentication"     : MPCM_ACCESS_TOKEN
        }
        with open(file_path, 'rb') as file_data:
            requests.post(url, data=file_data, headers=headers) 
