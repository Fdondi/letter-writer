/**
 * Local state persistence using localStorage.
 * 
 * Saves all application state to localStorage so it can be restored
 * on page load without needing to call the server.
 * 
 * IMPORTANT: The server session is the source of truth for server operations.
 * - Server reads from session to run phases (background, draft, refine)
 * - Server writes to session when phases complete
 * - Frontend must sync state to server session for operations to work
 * 
 * localStorage is for fast frontend restoration, but frontend must then
 * sync that restored state to the server session so the server has the data.
 */

const STORAGE_KEY = "letter_writer_state";
const STORAGE_VERSION = 1; // Increment if state structure changes

/**
 * Get full application state object from all state variables.
 * This should be called with all the state setters/getters from App.jsx
 */
export function getFullState(state) {
  return {
    version: STORAGE_VERSION,
    timestamp: Date.now(),
    
    // Input fields
    jobText: state.jobText || "",
    companyName: state.companyName || "",
    jobTitle: state.jobTitle || "",
    location: state.location || "",
    language: state.language || "",
    salary: state.salary || "",
    requirements: state.requirements || [],
    pointOfContact: state.pointOfContact || { name: "", role: "", contact_details: "", notes: "" },
    
    // Extracted data
    extractedData: state.extractedData || null,
    
    // UI state
    uiStage: state.uiStage || "input",
    activeTab: state.activeTab || "compose",
    assemblyVisible: state.assemblyVisible !== undefined ? state.assemblyVisible : true,
    showInput: state.showInput !== undefined ? state.showInput : true,
    showStyleBlade: state.showStyleBlade || false,
    
    // Session
    phaseSessionId: state.phaseSessionId || null,
    phaseSessions: state.phaseSessions || {},
    
    // Vendor data (from PhaseFlow registry)
    phaseRegistry: state.phaseRegistry || null,
    
    // Letters and costs
    letters: state.letters || {},
    vendorCosts: state.vendorCosts || {},
    vendorRefineCosts: state.vendorRefineCosts || {},
    failedVendors: state.failedVendors || {},
    
    // Document
    documentId: state.documentId || null,
    
    // Translation state
    jobTextViewLanguage: state.jobTextViewLanguage || "source",
    jobTextTranslations: state.jobTextTranslations || {},
  };
}

/**
 * Save state to localStorage.
 * Call this whenever important state changes.
 */
export function saveStateToLocal(state) {
  try {
    const fullState = getFullState(state);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fullState));
  } catch (e) {
    console.error("Failed to save state to localStorage:", e);
    // localStorage might be full or disabled - continue anyway
  }
}

/**
 * Load state from localStorage.
 * Returns null if no saved state exists or if version mismatch.
 */
export function loadStateFromLocal() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) {
      return null;
    }
    
    const state = JSON.parse(saved);
    
    // Check version compatibility
    if (state.version !== STORAGE_VERSION) {
      console.warn(`State version mismatch: ${state.version} vs ${STORAGE_VERSION}. Clearing old state.`);
      clearStateFromLocal();
      return null;
    }
    
    // Check if state is too old (optional - e.g., 30 days)
    const maxAge = 30 * 24 * 60 * 60 * 1000; // 30 days
    if (state.timestamp && Date.now() - state.timestamp > maxAge) {
      console.warn("Saved state is too old. Clearing.");
      clearStateFromLocal();
      return null;
    }
    
    return state;
  } catch (e) {
    console.error("Failed to load state from localStorage:", e);
    return null;
  }
}

/**
 * Clear state from localStorage.
 * Call when user explicitly clears or finishes.
 */
export function clearStateFromLocal() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) {
    console.error("Failed to clear state from localStorage:", e);
  }
}

/**
 * Restore state from localStorage to React state setters.
 * Returns the restored state object, or null if nothing was restored.
 * 
 * NOTE: After restoring, you must sync this state to the server session
 * so the server has the data for operations. Call syncStateToServer().
 */
export function restoreStateFromLocal(stateSetters) {
  const savedState = loadStateFromLocal();
  if (!savedState) {
    return null;
  }
  
  // Restore all state using the provided setters
  if (savedState.jobText !== undefined) stateSetters.setJobText(savedState.jobText);
  if (savedState.companyName !== undefined) stateSetters.setCompanyName(savedState.companyName);
  if (savedState.jobTitle !== undefined) stateSetters.setJobTitle(savedState.jobTitle);
  if (savedState.location !== undefined) stateSetters.setLocation(savedState.location);
  if (savedState.language !== undefined) stateSetters.setLanguage(savedState.language);
  if (savedState.salary !== undefined) stateSetters.setSalary(savedState.salary);
  if (savedState.requirements !== undefined) stateSetters.setRequirements(savedState.requirements);
  if (savedState.pointOfContact !== undefined) stateSetters.setPointOfContact(savedState.pointOfContact);
  if (savedState.extractedData !== undefined) stateSetters.setExtractedData(savedState.extractedData);
  if (savedState.uiStage !== undefined) stateSetters.setUiStage(savedState.uiStage);
  if (savedState.activeTab !== undefined) stateSetters.setActiveTab(savedState.activeTab);
  if (savedState.assemblyVisible !== undefined) stateSetters.setAssemblyVisible(savedState.assemblyVisible);
  if (savedState.showInput !== undefined) stateSetters.setShowInput(savedState.showInput);
  if (savedState.showStyleBlade !== undefined) stateSetters.setShowStyleBlade(savedState.showStyleBlade);
  if (savedState.phaseSessionId !== undefined) stateSetters.setPhaseSessionId(savedState.phaseSessionId);
  if (savedState.phaseSessions !== undefined) stateSetters.setPhaseSessions(savedState.phaseSessions || {});
  if (savedState.letters !== undefined) stateSetters.setLetters(savedState.letters || {});
  if (savedState.vendorCosts !== undefined) stateSetters.setVendorCosts(savedState.vendorCosts || {});
  if (savedState.vendorRefineCosts !== undefined) stateSetters.setVendorRefineCosts(savedState.vendorRefineCosts || {});
  if (savedState.failedVendors !== undefined) stateSetters.setFailedVendors(savedState.failedVendors || {});
  if (savedState.documentId !== undefined) stateSetters.setDocumentId(savedState.documentId);
  if (savedState.jobTextViewLanguage !== undefined) stateSetters.setJobTextViewLanguage(savedState.jobTextViewLanguage);
  if (savedState.jobTextTranslations !== undefined) stateSetters.setJobTextTranslations(savedState.jobTextTranslations || {});
  
  // Phase registry needs special handling - restore via populatePhaseShelf
  if (savedState.phaseRegistry && stateSetters.populatePhaseShelf) {
    Object.entries(savedState.phaseRegistry).forEach(([phaseName, vendors]) => {
      Object.entries(vendors).forEach(([vendor, data]) => {
        stateSetters.populatePhaseShelf(phaseName, vendor, data);
      });
    });
  }
  
  return savedState;
}

/**
 * Sync frontend state to server session.
 * 
 * This is critical - the server needs session data to run operations.
 * Call this after restoring from localStorage, and whenever important
 * state changes that the server needs to know about.
 */
export async function syncStateToServer(state) {
  try {
    // Extract vendor data first (handles cyclic references)
    let vendors = {};
    if (state.phaseRegistry) {
      try {
        vendors = extractVendorDataFromRegistry(state.phaseRegistry);
        console.log("[RESTORE] Extracted vendor data:", Object.keys(vendors), vendors);
      } catch (e) {
        console.warn("Failed to extract vendor data from phaseRegistry (may contain cyclic refs):", e);
        vendors = {};
      }
    } else {
      console.warn("[RESTORE] No phaseRegistry in state, cannot restore vendor data");
    }
    
    // Build the session data the server needs
    const sessionData = {
      job_text: state.jobText || "",
      cv_text: state.cvText || "",
      metadata: state.extractedData ? { common: state.extractedData } : {},
      vendors: vendors,
    };
    
    console.log("[RESTORE] Sending session data to server:", {
      has_job_text: !!sessionData.job_text,
      has_metadata: !!sessionData.metadata.common,
      vendor_count: Object.keys(sessionData.vendors).length,
      vendors: Object.keys(sessionData.vendors),
    });
    
    // Restore session on server
    const { fetchWithHeartbeat } = await import("./apiHelpers.js");
    const result_obj = await fetchWithHeartbeat("/api/phases/restore/", {
      method: "POST",
      body: JSON.stringify(sessionData),
    });
    
    const result = result_obj.data;
    console.log("[RESTORE] Session restored successfully:", result);
    return true;
  } catch (e) {
    console.error("Error syncing state to server:", e);
    return false;
  }
}

/**
 * Extract vendor data from phase registry for server session.
 * Handles cyclic references by only extracting serializable data.
 */
function extractVendorDataFromRegistry(phaseRegistry) {
  const vendors = {};
  
  // Phase registry structure: Array of phase objects with cardData
  // Each phase has: { phase: string, cardData: { vendor: data } }
  if (Array.isArray(phaseRegistry)) {
    phaseRegistry.forEach((phaseObj) => {
      if (phaseObj && phaseObj.cardData) {
        Object.entries(phaseObj.cardData).forEach(([vendor, data]) => {
          if (!vendors[vendor]) {
            vendors[vendor] = {};
          }
          // Only extract serializable fields (avoid React refs, functions, etc.)
          if (data && typeof data === 'object') {
            const serializable = {};
            // Extract known fields that the server expects
            if (data.top_docs !== undefined) serializable.top_docs = data.top_docs;
            if (data.company_report !== undefined) serializable.company_report = data.company_report;
            if (data.draft_letter !== undefined) serializable.draft_letter = data.draft_letter;
            if (data.final_letter !== undefined) serializable.final_letter = data.final_letter;
            if (data.feedback !== undefined) serializable.feedback = data.feedback;
            if (data.cost !== undefined) serializable.cost = data.cost;
            Object.assign(vendors[vendor], serializable);
          }
        });
      }
    });
  } else if (phaseRegistry && typeof phaseRegistry === 'object') {
    // Fallback: treat as { phaseName: { vendor: data } }
    Object.entries(phaseRegistry).forEach(([phaseName, vendorData]) => {
      if (vendorData && typeof vendorData === 'object') {
        Object.entries(vendorData).forEach(([vendor, data]) => {
          if (!vendors[vendor]) {
            vendors[vendor] = {};
          }
          // Only extract serializable fields
          if (data && typeof data === 'object') {
            const serializable = {};
            if (data.top_docs !== undefined) serializable.top_docs = data.top_docs;
            if (data.company_report !== undefined) serializable.company_report = data.company_report;
            if (data.draft_letter !== undefined) serializable.draft_letter = data.draft_letter;
            if (data.final_letter !== undefined) serializable.final_letter = data.final_letter;
            if (data.feedback !== undefined) serializable.feedback = data.feedback;
            if (data.cost !== undefined) serializable.cost = data.cost;
            Object.assign(vendors[vendor], serializable);
          }
        });
      }
    });
  }
  
  return vendors;
}

/**
 * Hook to auto-save state to localStorage whenever it changes.
 * 
 * Usage:
 *   useAutoSaveState({
 *     jobText, companyName, uiStage, ...all state values
 *   });
 */
export function useAutoSaveState(state, debounceMs = 500) {
  const { useEffect, useRef } = require("react");
  const timeoutRef = useRef(null);
  
  useEffect(() => {
    // Debounce saves to avoid excessive localStorage writes
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    
    timeoutRef.current = setTimeout(() => {
      saveStateToLocal(state);
    }, debounceMs);
    
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [state, debounceMs]);
}
