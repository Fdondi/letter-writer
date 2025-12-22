from django.urls import path
from . import views

urlpatterns = [
    path("refresh/", views.refresh_view, name="refresh"),
    path("process-job/", views.process_job_view, name="process_job"),
    path("phases/start/", views.start_phased_job_view, name="phases_start"),
    path("phases/draft/", views.draft_phase_view, name="phases_draft"),
    path("phases/refine/", views.refinement_phase_view, name="phases_refine"),
    path("vendors/", views.vendors_view, name="vendors"),
    path("style-instructions/", views.style_instructions_view, name="style_instructions"),
    path("translate/", views.translate_view, name="translate"),
    path("documents/", views.documents_view, name="documents"),
    path("documents/<str:document_id>/", views.document_detail_view, name="document_detail"),
    path("documents/<str:document_id>/negatives/", views.document_negatives_view, name="document_negatives"),
    path("documents/<str:document_id>/reembed/", views.document_reembed_view, name="document_reembed"),
] 