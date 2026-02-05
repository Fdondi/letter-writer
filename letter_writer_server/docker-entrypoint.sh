#!/bin/sh
set -e
cd /app
python letter_writer_server/manage.py migrate --noinput
# Set Django Site (id=1) domain from FRONTEND_URL so OAuth redirects and Host fix use the real host (not example.com)
python letter_writer_server/manage.py shell -c "
import os
from urllib.parse import urlparse
from django.contrib.sites.models import Site
url = os.environ.get('FRONTEND_URL', 'https://localhost:8443')
parsed = urlparse(url)
domain = parsed.netloc or 'localhost:8443'
s = Site.objects.get(id=1)
s.domain = domain
s.name = s.name or 'Letter Writer'
s.save()
print('Site domain set to', domain)
"
exec "$@"
