"""按业务日期固定目标文件，重复补跑覆盖同日结果，不追加重复记录。"""
import hashlib
from common import context,write_json

def main():
    params,day,output,data=context()
    # 同一业务日生成相同结果，与真正运行日期无关。
    total=int(hashlib.sha256(day.encode()).hexdigest()[:6],16)%10000
    result={'business_date':day,'total':total,'unit':str(params.get('unit','示例部门'))}
    target=data/'daily';target.mkdir(exist_ok=True)
    write_json(target/(day+'.json'),result)
    write_json(output/'daily-result.json',result)
    print('已保存业务日期',day,'结果；同日重跑覆盖同一个文件。',flush=True)
if __name__=='__main__':main()
