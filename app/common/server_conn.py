# from app.common.pyDes import do_decrypt as _p


class LinuxConfig:
    conn_info = {
        'ip': '76.13.45.52',
        'port': 22,
        'user': 'sysadmin',
        # 'password': _p('d4a0d164b4f301417df3fb9b71a993c4'),
    }
    conn_info1 = {
        'ip': '76.125.2.104',
        'port': 21,
        'user': 'ftpuser',
        # 'password': _p('3e335435a5f1afb4619c810122d5f709'),
        'password': 'PWDxt1b123',
    }


# from ftplib import FTP
# import os
#
# linux_conn = LinuxConfig()
# ftp = FTP()
# ftp.set_debuglevel(2)
# ftp.connect(linux_conn.conn_info1['ip'], linux_conn.conn_info1['port'])
# ftp.login(linux_conn.conn_info1['user'], linux_conn.conn_info1['password'])
# ftp.cwd('/xt1b/ftpuser/huawei_attendance/')
# file_list = ftp.nlst()
# print(file_list)
# for linux_file_name in file_list:
#     with open(linux_file_name, 'wb') as f:
#         res_ = ftp.retrbinary("RETR " + linux_file_name, f.write)
#         print(res_)
# data_list = list()
# for file_name in file_list:
#     with open(file_name, 'r') as f:
#         data_list.append(list(f.read().replace('null', ' ')))
#     os.remove(file_name)
# # print(data_list)
# for dict_str in data_list:
#     print(type(dict_str))
#     # print(type(eval(dict_str)))
# ftp.quit()
