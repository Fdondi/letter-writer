import React, { useState, useEffect } from "react";
import { Outlet } from "react-router-dom";
import StyleInstructionsBlade from "../components/StyleInstructionsBlade";
import OverlayPanel from "../components/OverlayPanel";
import PersonalDataPage from "../components/PersonalDataPage";
import DocumentsPage from "../components/DocumentsPage";
import SettingsPage from "../components/SettingsPage";
import CostsPage from "../components/CostsPage";
import AuthButton from "../components/AuthButton";
import AppVersionLabel from "../components/AppVersionLabel";
import CostDisplay from "../components/CostDisplay";
import LocalPricingWarningModal from "../components/LocalPricingWarningModal.jsx";
import SessionExpiredModal from "../components/SessionExpiredModal.jsx";
import { initializeCsrfToken } from "../utils/apiHelpers";
import { COST_TRACKING_ERROR_EVENT } from "../utils/costTracking";
import { scheduleGoogleOAuthRedirect } from "../utils/googleOAuthRedirect";
import { showNotification } from "../utils/apiNotifications";
import { useJobSession } from "../contexts/JobSessionContext";
import { getScaleConfig } from "../utils/competenceScales";
import { extractFormFieldsFromSessionState } from "../utils/sessionRehydrate";

export default function AppLayout() {
  const session = useJobSession();
  const { isAuthenticated, checkingAuth, showSessionExpiredModal } = session;

  // Overlay flags (layout-local, dies with AppLayout)
  const [showStyleBlade, setShowStyleBlade] = useState(false);
  const [instructionsUpstreamPending, setInstructionsUpstreamPending] = useState(false);
  const [showCvOverlay, setShowCvOverlay] = useState(false);
  const [showDocumentsOverlay, setShowDocumentsOverlay] = useState(false);
  const [showSettingsOverlay, setShowSettingsOverlay] = useState(false);
  const [showCostsOverlay, setShowCostsOverlay] = useState(false);
  const [costTrackingError, setCostTrackingError] = useState(null);

  // CSRF + cost tracking on mount
  useEffect(() => {
    initializeCsrfToken().catch((e) => console.warn("CSRF init:", e));
    const onCostErr = (event) => {
      const message = event?.detail?.message;
      if (message) setCostTrackingError(message);
    };
    window.addEventListener(COST_TRACKING_ERROR_EVENT, onCostErr);
    return () => window.removeEventListener(COST_TRACKING_ERROR_EVENT, onCostErr);
  }, []);

  // Warn on unload when unsaved work exists
  useEffect(() => {
    if (isAuthenticated !== true) return undefined;
    const hasUnsaved = session.hasUnsavedComposeInput;
    if (!hasUnsaved) return undefined;
    const handler = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isAuthenticated, session.hasUnsavedComposeInput]);

  if (checkingAuth) {
    return (
      <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh", backgroundColor: "var(--bg-color)", color: "var(--text-color)" }}>
        <div style={{ padding: "12px 20px", display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 600, color: "var(--text-color)" }}>Letter Writer</h1>
          <AppVersionLabel />
        </div>
        <div style={{ flex: 1, display: "flex", justifyContent: "center", alignItems: "center" }}>
          <div>Checking authentication...</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "100vh", backgroundColor: "var(--bg-color)", color: "var(--text-color)", padding: "20px" }}>
        <div style={{ maxWidth: "400px", width: "100%", padding: "40px", backgroundColor: "var(--panel-bg)", border: "1px solid var(--border-color)", borderRadius: "8px", boxShadow: "0 4px 12px rgba(0,0,0,0.1)", textAlign: "center" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 8, flexWrap: "wrap", marginBottom: "10px" }}>
            <h1 style={{ margin: 0, fontSize: "24px", fontWeight: 600 }}>Letter Writer</h1>
            <AppVersionLabel />
          </div>
          <p style={{ marginBottom: "30px", color: "var(--text-color)", opacity: 0.8 }}>Sign in to continue</p>
          <button
            onClick={() => scheduleGoogleOAuthRedirect()}
            style={{ width: "100%", padding: "12px 24px", fontSize: "16px", fontWeight: 600, backgroundColor: "#4285f4", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
          >
            Sign in with Google
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 20, backgroundColor: "var(--bg-color)", color: "var(--text-color)", minHeight: "100vh", display: "flex", flexDirection: "column", boxSizing: "border-box" }}>
      {costTrackingError && (
        <div role="alert" style={{ marginBottom: 12, padding: "10px 14px", backgroundColor: "var(--error-bg, #fef2f2)", border: "1px solid var(--error-border, #fecaca)", borderRadius: 6, color: "var(--error-text, #b91c1c)", fontSize: 13, display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
          <span><strong>Cost tracking unavailable:</strong> {costTrackingError}</span>
          <button type="button" onClick={() => setCostTrackingError(null)} style={{ flexShrink: 0, border: "none", background: "transparent", color: "inherit", cursor: "pointer", fontSize: 16, lineHeight: 1 }} aria-label="Dismiss cost tracking warning">×</button>
        </div>
      )}

      <div style={{ position: "relative", marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
            <h1 style={{ margin: 0, color: "var(--text-color)" }}>Letter Writer</h1>
            <AppVersionLabel />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button onClick={() => setShowStyleBlade(true)} style={{ padding: "8px 12px", border: "1px solid var(--border-color)", borderRadius: "4px", backgroundColor: "var(--button-bg)", color: "var(--button-text)", cursor: "pointer", fontSize: "14px", position: "relative" }}>
              AI Instructions
              {instructionsUpstreamPending && (
                <span title="Default instructions updated" style={{ position: "absolute", top: 4, right: 4, width: 8, height: 8, borderRadius: "50%", backgroundColor: "#6366f1" }} />
              )}
            </button>
            <button onClick={() => setShowCvOverlay(true)} style={{ padding: "8px 12px", border: "1px solid var(--border-color)", borderRadius: "4px", backgroundColor: showCvOverlay ? "#3b82f6" : "var(--button-bg)", color: showCvOverlay ? "white" : "var(--button-text)", cursor: "pointer", fontSize: "14px" }}>Your CV</button>
            <button onClick={() => setShowDocumentsOverlay(true)} style={{ padding: "8px 12px", border: "1px solid var(--border-color)", borderRadius: "4px", backgroundColor: showDocumentsOverlay ? "#3b82f6" : "var(--button-bg)", color: showDocumentsOverlay ? "white" : "var(--button-text)", cursor: "pointer", fontSize: "14px" }}>Previous Examples</button>
            <button onClick={() => setShowSettingsOverlay(true)} style={{ padding: "8px 12px", border: "1px solid var(--border-color)", borderRadius: "4px", backgroundColor: showSettingsOverlay ? "#3b82f6" : "var(--button-bg)", color: showSettingsOverlay ? "white" : "var(--button-text)", cursor: "pointer", fontSize: "14px" }}>Settings</button>
            <CostDisplay onNavigate={() => setShowCostsOverlay(true)} />
            <AuthButton />
          </div>
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}><Outlet /></div>

      <OverlayPanel title="Your CV" isOpen={showCvOverlay} onClose={() => setShowCvOverlay(false)}><PersonalDataPage /></OverlayPanel>
      <OverlayPanel title="Previous Examples" isOpen={showDocumentsOverlay} onClose={() => setShowDocumentsOverlay(false)}><DocumentsPage /></OverlayPanel>
      <OverlayPanel title="Settings" isOpen={showSettingsOverlay} onClose={() => setShowSettingsOverlay(false)}>
        <SettingsPage
          vendors={session.vendors}
          selectedVendors={session.selectedVendors}
          setSelectedVendors={session.setSelectedVendors}
          setBackgroundModels={session.setBackgroundModels}
          onCompetenceScalesChange={() => session.setCompetenceScaleConfig(getScaleConfig())}
          guardBeforeEnablingLocal={session.guardBeforeEnablingLocal}
          onSessionRestored={(sessionState, sessionId) => {
            const fields = extractFormFieldsFromSessionState(sessionState);
            if (fields) {
              if (fields.jobText !== undefined) session.setJobText(fields.jobText);
              if (fields.companyName !== undefined) session.setCompanyName(fields.companyName);
              if (fields.jobTitle !== undefined) session.setJobTitle(fields.jobTitle);
              if (fields.location !== undefined) session.setLocation(fields.location);
              if (fields.language !== undefined) session.setLanguage(fields.language);
              if (fields.salary !== undefined) session.setSalary(fields.salary);
              if (fields.additionalUserInfo !== undefined) session.setAdditionalUserInfo(fields.additionalUserInfo);
              if (fields.additionalCompanyInfo !== undefined) session.setAdditionalCompanyInfo(fields.additionalCompanyInfo);
              if (fields.hireProblem !== undefined) session.setHireProblem(fields.hireProblem);
              if (fields.requirements !== undefined) session.setRequirements(fields.requirements);
              if (fields.competences !== undefined) session.setCompetences(fields.competences);
              if (fields.pointOfContact !== undefined) {
                session.setPointOfContact(fields.pointOfContact);
                const poc = fields.pointOfContact;
                if (String(poc?.name || "").trim() || String(poc?.role || "").trim() || String(poc?.contact_details || "").trim() || String(poc?.notes || "").trim() || String(poc?.company || "").trim()) {
                  session.setShowPointOfContact(true);
                }
              }
              if (String(fields.additionalUserInfo || "").trim() || String(fields.additionalCompanyInfo || "").trim()) {
                session.setShowAdditionalInfo(true);
              }
            }
            if (sessionId) session.setPhaseSessionId(sessionId);
            showNotification("Session restored from host backup");
            setShowSettingsOverlay(false);
          }}
        />
      </OverlayPanel>
      <OverlayPanel title="API Costs" isOpen={showCostsOverlay} onClose={() => setShowCostsOverlay(false)}><CostsPage /></OverlayPanel>

      <LocalPricingWarningModal
        isOpen={session.localPricingModalOpen}
        onContinue={session.handleLocalPricingModalContinue}
        onCancel={session.handleLocalPricingModalCancel}
        dismissChecked={session.localPricingDismissChecked}
        onDismissCheckedChange={session.setLocalPricingDismissChecked}
      />

      <SessionExpiredModal isOpen={showSessionExpiredModal} />

      <StyleInstructionsBlade
        isOpen={showStyleBlade}
        onClose={() => setShowStyleBlade(false)}
        onUpstreamStatusChange={setInstructionsUpstreamPending}
      />
    </div>
  );
}
