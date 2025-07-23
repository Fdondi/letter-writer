from django.urls import path, include

urlpatterns = [
    path("api/", include("letter_writer_server.api.urls")),
] 