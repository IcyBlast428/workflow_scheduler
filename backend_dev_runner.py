import os

os.environ.setdefault("WFS_ENV", "development")
os.environ.setdefault("WFS_ENABLE_SCHEDULER", "true")

from run import app


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8008, threaded=True)
