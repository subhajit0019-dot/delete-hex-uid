import os
import sys

# Add project root directory to Python module search path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from dashboard import app

# Vercel serverless WSGI application entrypoint
# The 'app' variable is automatically discovered by @vercel/python runtime
application = app
