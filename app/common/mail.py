# coding = utf-8
import os, io, re
import smtplib
import pandas as pd
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import parseaddr, formataddr
from email.mime.base import MIMEBase
from email import encoders
from app.common.database import NewDB
from app.common.utils import get_local_ip
from app.common.nacos import Nacos

def _format_addr(s):
    name, addr = parseaddr(s)
    return formataddr((Header(name, 'utf-8').encode(), addr))

def send_mail(to_receivers, subject, body, attachments_files=[], cc_receivers=[], image_files=[], sender_name="运维服务平台-WFS"):
    mail_server = smtplib.SMTP('mails.icbc', 25)
    sender_addr = 'immp@dc.icbc.com.cn'
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = _format_addr(sender_name + '<' + sender_addr + '>')
    # msg['To'] = ','.join(to_receivers)
    msg['To'] = ','.join([_format_addr(s) for s in to_receivers])
    # msg['Cc'] = ','.join(cc_receivers)
    msg['Cc'] = ','.join([_format_addr(s) for s in cc_receivers])
    receivers = to_receivers + cc_receivers
    footer = """
    <br/>
    <br/>
    <hr>
    <font size="1">Powered by WFS({ip})</font>
    """.format(ip = get_local_ip())
    body = body + footer
    pure_text = MIMEText(body, 'html', 'utf-8')
    msg.attach(pure_text)
    for image_file in image_files:
        image = MIMEImage(open(image_file, "rb").read())
        imageid = re.search(r".+/(?P<name>.+)\.(?P<suffix>.+)$", image_file).group("name")
        image.add_header("Content-ID", imageid)
        msg.attach(image)
    for attachment_file in attachments_files:
        # filePath = re.search(r"^.*/", attachment_file).group(0)
        # fileName = re.search(r"[^/]*$", attachment_file).group(0)
        # file_name_chs_flag = False
        # for char in fileName:
        #     if "\u4e00" <= char <= "\u9fff":
        #         file_name_chs_flag = True
        #         break
        if isinstance(attachment_file, io.BytesIO):
            # 不保存文件形式，以二进制流对象传值
            attachment = MIMEBase('application', 'octet-stream')
            attachment.set_payload(attachment_file.getvalue())
            encoders.encode_base64(attachment)
            # 在流对象中创建obj.name='文件名'
            attachment.add_header('Content-Disposition', 'attachment', filename=attachment_file.name)
        else:
            # if file_name_chs_flag:
            #     attachment = MIMEApplication(open(attachment_file.encode("utf-8").decode("latin-1"), 'rb').read())
            # else:
                # attachment = MIMEApplication(open(attachment_file, 'rb').read())
            attachment = MIMEApplication(open(attachment_file, 'rb').read())
            attachment.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_file))
        msg.attach(attachment)
    mail_server.sendmail(sender_addr, receivers, msg.as_string())
    mail_server.quit()

def get_mail_list(job_group = "default", job_name = "default", injob_part = "default"):
    # init database connection
    immpdb_obj = NewDB("mysql_immpdb")
    immpdb_obj.get_engine()
    immpdb_connection = immpdb_obj.get_connection()
    
    # return all email of people in 系统一部
    if job_name == "default" and job_group == "default":
        mail_receivers_query_sql = "select email from immp_cfg_user_mail_sms where department = '系统一部'"
        mail_receivers_df = pd.read_sql(mail_receivers_query_sql, con = immpdb_connection)
        return mail_receivers_df["email"].tolist()
    
    # get raw data from nacos
    receivers_dic = Nacos().get_nacos_configs(tenant= "wfs", data_id= job_name + ".json", group= job_group)
    # split partion
    receivers_dic = receivers_dic[injob_part]
    # split sms and mail receivers
    mail_receivers_dic = {}
    for receivers_dic_key in receivers_dic.keys():
        if re.search(r"^mail.*", receivers_dic_key) != None:
            mail_receivers_dic[receivers_dic_key] = receivers_dic[receivers_dic_key]
    # split individual and group receivers
    mail_receivers_individual_list = []
    mail_receivers_group_list = []
    for mail_receivers_dic_key in mail_receivers_dic.keys():
        if re.search(r".*?individual$", mail_receivers_dic_key) != None:
            mail_receivers_individual_list = mail_receivers_dic[mail_receivers_dic_key]
        if re.search(r".*?group$", mail_receivers_dic_key) != None:
            mail_receivers_group_list = mail_receivers_dic[mail_receivers_dic_key]
    
    # for individual
    mail_receivers_individual_mail_list = []
    if len(mail_receivers_individual_list) != 0:
        mail_receivers_individual_aamid_list = [aamid for person_dic in mail_receivers_individual_list for aamid in person_dic.keys()]
        mail_receivers_individual_aamid_query_clause_str = '\'' + "','".join(mail_receivers_individual_aamid_list) + '\''
        mail_receivers_individual_aamid_query_sql = f"select email from immp_cfg_user_mail_sms where aamid in ({mail_receivers_individual_aamid_query_clause_str})"
        mail_receivers_individual_df = pd.read_sql(mail_receivers_individual_aamid_query_sql, con = immpdb_connection)
        mail_receivers_individual_mail_list = mail_receivers_individual_df["email"].tolist()
    # for group
    mail_receivers_group_mail_list = []
    if len(mail_receivers_group_list) != 0:
        mail_receivers_group_query_clause_str = '\'' + "','".join(mail_receivers_group_list) + '\''
        mail_receivers_group_query_sql = f"select email from immp_cfg_group_mail where cnname in ({mail_receivers_group_query_clause_str})"
        mail_receivers_group_df = pd.read_sql(mail_receivers_group_query_sql, con = immpdb_connection)
        mail_receivers_group_mail_list = mail_receivers_group_df["email"].tolist()
    
    # combine individual and group receivers
    mail_receivers_list = mail_receivers_individual_mail_list + mail_receivers_group_mail_list
    # remove duplicates
    mail_receivers_list = list(set(mail_receivers_list))
    return mail_receivers_list
