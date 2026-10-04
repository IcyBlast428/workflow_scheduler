"""演示数据读取、条件判断、逐条处理和结果保存。"""
from worker import transform


def main(rows):
    """逐条转换有效数据，输出处理结果。"""
    results = []
    for row in rows:
        if row > 0:
            results.append(transform(row))
        else:
            continue
    try:
        print(results)
    except ValueError:
        print('输出失败')
    finally:
        print('处理结束')
    return results


if __name__ == '__main__':
    main([1, 0, 2])
