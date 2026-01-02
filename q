[1mdiff --git a/letter_writer_server/api/views.py b/letter_writer_server/api/views.py[m
[1mindex d5ba8d8..b330798 100644[m
[1m--- a/letter_writer_server/api/views.py[m
[1m+++ b/letter_writer_server/api/views.py[m
[36m@@ -327,6 +327,9 @@[m [mdef update_session_common_data_view(request: HttpRequest):[m
         return JsonResponse({"detail": "session_id is required"}, status=400)[m
 [m
     job_text = data.get("job_text")[m
[32m+[m[32m    if not job_text:[m
[32m+[m[32m        return JsonResponse({"detail": "job_text is required"}, status=400)[m
[32m+[m[41m    [m
     cv_text = data.get("cv_text")[m
     if cv_text is None:[m
         cv_path = Path(env_default("CV_PATH", "cv.md"))[m
[36m@@ -340,11 +343,13 @@[m [mdef update_session_common_data_view(request: HttpRequest):[m
         [m
         # Load existing session to preserve other fields[m
         existing = load_session_common_data(session_id)[m
[31m-        existing_metadata = existing["metadata"] if existing else {}[m
[32m+[m[32m        existing_metadata = existing.get("metadata", {}) if existing else {}[m
         [m
         # Build common metadata from individual fields (if provided)[m
         # These are the fields the user sees in the webpage[m
         common_metadata = existing_metadata.get("common", {})[m
[32m+[m[32m        if not isinstance(common_metadata, dict):[m
[32m+[m[32m            common_metadata = {}[m
         [m
         # Update metadata fields if provided in request[m
         if "company_name" in data:[m
[36m@@ -360,8 +365,10 @@[m [mdef update_session_common_data_view(request: HttpRequest):[m
         if "requirements" in data:[m
             common_metadata["requirements"] = data["requirements"][m
         [m
[31m-        # Save updated metadata[m
[31m-        existing_metadata["common"] = common_metadata[m
[32m+[m[32m        # Ensure "common" key always exists in metadata (even if empty)[m
[32m+[m[32m        if "common" not in existing_metadata:[m
[32m+[m[32m            existing_metadata["common"] = {}[m
[32m+[m[32m        existing_metadata["common"].update(common_metadata)[m
         [m
         # Save common data (job_text, cv_text, and metadata)[m
         save_session_common_data([m
[36m@@ -411,9 +418,13 @@[m [mdef background_phase_view(request: HttpRequest, vendor: str):[m
         if common_data is None:[m
             raise ValueError(f"Session {session_id} not found. Common data must be saved by extraction phase or 'start phases' API call first.")[m
         [m
[32m+[m[32m        # Ensure metadata exists and has the expected structure[m
[32m+[m[32m        if "metadata" not in common_data:[m
[32m+[m[32m            common_data["metadata"] = {}[m
[32m+[m[41m        [m
         # Metadata must exist in common store (created by extraction phase or session call)[m
         if "common" not in common_data["metadata"]:[m
[31m-            raise ValueError(f"Metadata not found in session. Please run extraction first or provide extraction data via /api/phases/session/")[m
[32m+[m[32m            raise ValueError(f"Metadata not found in session. Please run extraction first or provide extraction data via /api/phases/session/. Session metadata keys: {list(common_data.get('metadata', {}).keys())}")[m
         [m
         # Run background phase for this vendor (writes only vendor-specific data)[m
         vendor_state = _run_background_phase(session_id, vendors[0], common_data)[m
