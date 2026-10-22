"""无需第三方依赖；将 main.py 放在 ZIP 根目录即可发布。"""
from datetime import datetime


def main():
    print(f"任务开始：{datetime.now().isoformat(timespec='seconds')}", flush=True)
    total = sum(range(1, 101))
    print(f"1 到 100 的合计：{total}", flush=True)


if __name__ == '__main__':
    main()
