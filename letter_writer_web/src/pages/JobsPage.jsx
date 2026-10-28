import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import OpportunitiesPage from "../components/OpportunitiesPage";
import { useJobSession } from "../contexts/JobSessionContext";
import { harnessRestorePath } from "../utils/harnessFixtureBoot";
import { showNotification } from "../utils/apiNotifications";

/** `/opportunities`: the job pipeline. Opening a ready job restores its drafts like a backup. */
export default function JobsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const session = useJobSession();

  return (
    <OpportunitiesPage
      highlightId={searchParams.get("id")}
      onOpened={(sessionState, sessionId, opportunity) => {
        // A completed job's drafts are the candidates: jump straight to crafting the final letter.
        const result = session.applyBackupRestore(sessionState, sessionId, { forceAssembly: true });
        const path = harnessRestorePath(result);
        navigate(path, { state: path === "/" ? {} : { rehydrated: true } });
        if (result?.restored) {
          showNotification(`Opened the drafts for ${opportunity?.title || "the job"}`);
        }
      }}
    />
  );
}
