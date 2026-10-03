import os

os.environ.setdefault("WFS_ENV", "development")
os.environ.setdefault("WFS_ENABLE_SCHEDULER", "true")

from run import app


if __name__ == "__main__":
    app.run(debug=False, host=os.environ.get('WFS_HOST', '127.0.0.1'), port=int(os.environ.get('WFS_PORT', '8008')), threaded=True)
