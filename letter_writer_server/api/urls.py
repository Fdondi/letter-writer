from django.urls import path
from . import views

urlpatterns = [
    path("refresh/", views.refresh_view, name="refresh"),
    path("process-job/", views.process_job_view, name="process_job"),
    path("vendors/", views.vendors_view, name="vendors"),
    path("style-instructions/", views.style_instructions_view, name="style_instructions"),
] 