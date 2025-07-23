import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'letter_writer_server.settings')

application = get_wsgi_application() 