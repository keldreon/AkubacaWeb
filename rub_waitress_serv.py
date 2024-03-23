import os
from waitress import serve
from flask_app import app

serve(app, host='0.0.0.0', port=8080)