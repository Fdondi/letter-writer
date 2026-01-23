from django.urls import path
from . import views

urlpatterns = [
    # Authentication endpoints
    path("auth/csrf-token/", views.csrf_token_view, name="csrf_token"),
    path("auth/user/", views.current_user_view, name="current_user"),
    path("auth/status/", views.auth_status_view, name="auth_status"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    # API endpoints
    path("refresh/", views.refresh_view, name="refresh"),
    path("process-job/", views.process_job_view, name="process_job"),
    path("extract/", views.extract_view, name="extract"),
    path("phases/init/", views.init_session_view, name="phases_init"),
    path("phases/session/", views.update_session_common_data_view, name="phases_session"),
    path("phases/restore/", views.restore_session_view, name="phases_restore"),
    path("phases/state/", views.get_session_state_view, name="phases_state"),
    path("phases/clear/", views.clear_session_view, name="phases_clear"),
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
    path("personal-data/", views.personal_data_view, name="personal_data"),
    # Debug endpoints for spam prevention
    path("debug/in-flight-requests/", views.debug_in_flight_requests_view, name="debug_in_flight"),
    path("debug/clear-in-flight-requests/", views.debug_clear_in_flight_requests_view, name="debug_clear_in_flight"),
    # Cost tracking
    path("costs/pending/", views.cost_summary_view, name="cost_pending"),
    path("costs/flush/", views.cost_flush_view, name="cost_flush"),
    path("costs/user/", views.cost_user_view, name="cost_user"),
    path("costs/global/", views.cost_global_view, name="cost_global"),
] 