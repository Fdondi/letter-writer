import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'letter_writer_server.settings')

application = get_asgi_application() 