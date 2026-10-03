import os
from app import create_app
app = create_app()  # production/development

if __name__ == '__main__':
    app.run(debug=False, port=int(os.environ.get('WFS_PORT', '8008')), host=os.environ.get('WFS_HOST', '127.0.0.1'), threaded=True)
