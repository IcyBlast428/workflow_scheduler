"""Reject IE before authentication or application bundles are loaded."""
from pathlib import Path
import re

from flask import jsonify, request, send_file

IE_USER_AGENT = re.compile(r'MSIE\s|Trident/', re.IGNORECASE)
MESSAGE = '不支持 Internet Explorer（IE），请使用 Chrome 内核浏览器，例如 Google Chrome 或新版 Microsoft Edge；如处于 IE 模式，请退出后重试。'


def reject_unsupported_browser(app):
    if not IE_USER_AGENT.search(request.headers.get('User-Agent', '')):
        return None
    if request.path.startswith('/api/'):
        response = jsonify(code='UNSUPPORTED_BROWSER', message=MESSAGE)
    else:
        response = send_file(Path(app.root_path)/'dist/unsupported-browser.html',
                             mimetype='text/html', conditional=False, etag=False)
        response.headers.pop('Last-Modified', None)
    response.status_code = 403
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response
