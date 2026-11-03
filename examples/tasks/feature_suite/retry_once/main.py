"""可重复执行的无外部副作用示例：首次失败，平台重试时成功。"""
import os
from common import context,write_json

def main():
    params,day,output,data=context()
    source=os.environ.get('WFS_EXECUTION_SOURCE','manual')
    print('执行来源：',source,'业务日期：',day,flush=True)
    if params.get('simulate_failure',True) and source not in ('retry','trial'):
        raise RuntimeError('预期的演示失败：如已开启一次自动重试，稍后将生成重试请求。')
    write_json(output/'retry-result.json',{'business_date':day,'source':source,'success':True})
    print('执行成功。',flush=True)
if __name__=='__main__':main()
