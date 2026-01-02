from django.urls import path
from . import views

urlpatterns = [
    path("refresh/", views.refresh_view, name="refresh"),
    path("process-job/", views.process_job_view, name="process_job"),
    path("extract/", views.extract_view, name="extract"),
    path("phases/init/", views.init_session_view, name="phases_init"),
    path("phases/session/", views.update_session_common_data_view, name="phases_session"),
    path("phases/background/<str:vendor>/", views.background_phase_view, name="phases_background"),
    path("phases/draft/<str:vendor>/", views.draft_phase_view, name="phases_draft"),
    path("phases/refine/<str:vendor>/", views.refinement_phase_view, name="phases_refine"),
    path("vendors/", views.vendors_view, name="vendors"),
    path("style-instructions/", views.style_instructions_view, name="style_instructions"),
    path("translate/", views.translate_view, name="translate"),
    path("documents/", views.documents_view, name="documents"),
    path("documents/<str:document_id>/", views.document_detail_view, name="document_detail"),
    path("documents/<str:document_id>/negatives/", views.document_negatives_view, name="document_negatives"),
    path("documents/<str:document_id>/reembed/", views.document_reembed_view, name="document_reembed"),
    # Debug endpoints for spam prevention
    path("debug/in-flight-requests/", views.debug_in_flight_requests_view, name="debug_in_flight"),
    path("debug/clear-in-flight-requests/", views.debug_clear_in_flight_requests_view, name="debug_clear_in_flight"),
] 