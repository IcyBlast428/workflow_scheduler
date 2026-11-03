"""观察排队、日志、取消、超时、CPU 曲线；默认仅短暂等待。"""
import math
import time
from common import context,write_json

def main():
    params,day,output,data=context()
    seconds=max(1,min(30,int(params.get('seconds',5))))
    cpu=max(0,min(2,float(params.get('cpu_seconds',0))))
    for step in range(seconds):
        print(f'进度 {step+1}/{seconds}',flush=True);time.sleep(1)
    deadline=time.monotonic()+cpu;value=0.0
    while time.monotonic()<deadline:value+=math.sqrt(12345)
    write_json(output/'progress.json',{'wait_seconds':seconds,'cpu_seconds':cpu,'done':True})
    print('示例完成。',flush=True)
if __name__=='__main__':main()
