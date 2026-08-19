/**
 * PHASED EXECUTION MODEL - ARCHITECTURAL OVERVIEW
 *
 * This component implements a reactive, "Passive Card" model.
 *
 * DATA FLOW:
 * 1. Actor (App.jsx): Launches API calls (initial start, approval, or retry).
 * 2. Shelf (cardData): App.jsx populates the 'shelf' for the target phase.
 * 3. Observer (VendorCardWrapper): Detects data on the shelf and renders.
 *
 * PHASES IN THIS PIPELINE:
 * - PLAN: Strategic outline (strengths, weaknesses to frame, layout) from /api/phases/plan/.
 *         Approving calls /api/phases/draft/ with the approved plan text.
 * - DRAFT: Draft letter + feedback (from /api/phases/draft/). Approving calls /api/phases/refine/
 *          for the final letter.
 * - ASSEMBLY: A separate UI rendered by App.jsx that holds the result of the refine call.
 *
 * KEY RULES:
 * - NO CARD FETCHES ITS OWN DATA: VendorCardWrapper has no fetch logic.
 * - LOADING STATE: If a phase is 'approved' but its shelf is empty, the
 *   card automatically shows "Loading...".
 * - RE-RENDERING: App.jsx triggers a re-render of PhaseFlow whenever
 *   the shelf is updated.
 */
import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";
import { phases as phaseModules } from "./phases";
import PhaseSection from "./phase-flow/PhaseSection";
import VendorCardWrapper from "./phase-flow/VendorCardWrapper";
import { CardStatus } from "./phase-flow/cardStatus";

/**
 * Bump when the vendor phase pipeline (order, phase names, or phase modules) changes.
 * PhaseFlow only rebuilt `phasesRef` when the vendor *count* changed, so HMR / same-count
 * navigations kept a stale single-phase tree (wrong section titles and shelf keys).
 */
const PHASE_FLOW_SCHEMA_VERSION = 3;

/** After all plan models have returned (success or error), auto-run plan approval for ready cards. */
const PLAN_AUTO_APPROVE_MS = 30000;

function transformToPhaseStructure(vendorsList, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters, includePlanStep = true) {
  const phaseOrder = includePlanStep ? ["plan", "draft"] : ["draft"];

  const phaseObjects = phaseOrder.map((phaseName) => {
    const existingCounters = phaseCounters && phaseCounters[phaseName];
    const vendorCount = vendorsList.length;

    let readyCount = existingCounters?.readyCount ?? 0;
    let pendingCount = existingCounters?.pendingCount ?? vendorCount;

    if (!existingCounters) {
      pendingCount = vendorCount;
      readyCount = 0;

      setPhaseCounters(prev => ({
        ...prev,
        [phaseName]: { readyCount, pendingCount }
      }));
    }

    const phaseObj = {
      phase: phaseName,
      previous: null,
      next: null,
      readyCount,
      pendingCount,
      cardData: {},
      cardErrors: {},
      approvedVendors: new Set(),
      registerStatus: (vendor, status) => {
        switch (status) {
          case CardStatus.PENDING:
            if (phaseObj.readyCount > 0) {
              phaseObj.readyCount--;
            }
            break;
          case CardStatus.READY:
            phaseObj.readyCount++;
            break;
          case CardStatus.APPROVED:
            if (phaseObj.readyCount > 0) {
              phaseObj.readyCount--;
            }
            if (phaseObj.pendingCount > 0) {
              phaseObj.pendingCount--;
            }
            break;
          default:
            break;
        }

        setPhaseCounters(prev => ({
          ...prev,
          [phaseName]: { readyCount: phaseObj.readyCount, pendingCount: phaseObj.pendingCount }
        }));

        setPhaseUpdateTrigger(prev => prev + 1);
      },
      approveAllReady: () => [],
    };

    if (phaseName === "plan") {
      phaseObj.planApproveRunners = new Map();
    }

    return phaseObj;
  });

  phaseObjects.forEach((phaseObj, index) => {
    phaseObj.previous = index > 0 ? phaseObjects[index - 1] : null;
    phaseObj.next = index < phaseObjects.length - 1 ? phaseObjects[index + 1] : null;
  });

  return phaseObjects;
}

export default function PhaseFlow({
  vendorsList,
  onEditChange,
  onApprove,
  onApproveAll,
  includePlanStep = true,
  sessionId,
  documentId = null,
  draftFeedbackRegistryRef = null,
  flowResetKey = 0,
  onPhaseComplete,
  onRegisterPhases,
  onClearPhaseFetchError,
  onRetryPhaseFetch,
}) {
  const [collapsedPhases, setCollapsedPhases] = useState({
    plan: false,
    draft: false,
  });

  const [expandedCard, setExpandedCard] = useState(null);
  const toggleExpand = useCallback((phase, vendor) => {
    setExpandedCard((prev) =>
      prev?.phase === phase && prev?.vendor === vendor ? null : { phase, vendor }
    );
  }, []);
  const closeExpand = useCallback(() => setExpandedCard(null), []);

  const [phaseUpdateTrigger, setPhaseUpdateTrigger] = useState(0);

  const planVendorSettledAtRef = useRef({});
  const prevPlanVendorSettledRef = useRef({});
  const planAutoApproveTimerRef = useRef(null);
  const autoCollapsedPlanForDraftRef = useRef(false);

  useEffect(() => {
    setCollapsedPhases({ plan: false, draft: false });
    planVendorSettledAtRef.current = {};
    prevPlanVendorSettledRef.current = {};
    autoCollapsedPlanForDraftRef.current = false;
    if (planAutoApproveTimerRef.current) {
      clearTimeout(planAutoApproveTimerRef.current);
      planAutoApproveTimerRef.current = null;
    }
  }, [flowResetKey]);

  useEffect(() => {
    const phases = phasesRef.current;
    const planPhase = phases?.find((p) => p.phase === "plan");
    if (!planPhase) return;
    const draftVisible = (planPhase.approvedVendors?.size ?? 0) > 0;
    if (!draftVisible || autoCollapsedPlanForDraftRef.current) return;
    autoCollapsedPlanForDraftRef.current = true;
    setCollapsedPhases((prev) => ({ ...prev, plan: true }));
  }, [phaseUpdateTrigger, flowResetKey]);

  useEffect(() => {
    return () => {
      if (planAutoApproveTimerRef.current) {
        clearTimeout(planAutoApproveTimerRef.current);
        planAutoApproveTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const phases = phasesRef.current;
    const planPhase = phases?.find((p) => p.phase === "plan");
    if (!planPhase?.planApproveRunners || vendorsList.length === 0) {
      if (planAutoApproveTimerRef.current) {
        clearTimeout(planAutoApproveTimerRef.current);
        planAutoApproveTimerRef.current = null;
      }
      return;
    }

    const now = Date.now();

    for (const v of vendorsList) {
      const data = planPhase.cardData[v];
      const err = planPhase.cardErrors?.[v];
      const hasPlanText =
        data &&
        typeof data.letter_plan === "string" &&
        data.letter_plan.trim().length > 0;
      const settled = Boolean(hasPlanText || err);
      const prev = prevPlanVendorSettledRef.current[v];
      if (settled && !prev) {
        planVendorSettledAtRef.current[v] = now;
      }
      if (!settled) {
        delete planVendorSettledAtRef.current[v];
        prevPlanVendorSettledRef.current[v] = false;
      } else {
        prevPlanVendorSettledRef.current[v] = true;
      }
    }

    const allSettled = vendorsList.every((v) => {
      const data = planPhase.cardData[v];
      const err = planPhase.cardErrors?.[v];
      const hasPlanText =
        data &&
        typeof data.letter_plan === "string" &&
        data.letter_plan.trim().length > 0;
      return hasPlanText || err;
    });

    if (planAutoApproveTimerRef.current) {
      clearTimeout(planAutoApproveTimerRef.current);
      planAutoApproveTimerRef.current = null;
    }

    if (!allSettled) return;

    const times = vendorsList.map((v) => planVendorSettledAtRef.current[v]).filter(Boolean);
    const lastReturn = times.length ? Math.max(...times) : 0;
    if (!lastReturn) return;

    const delay = Math.max(0, PLAN_AUTO_APPROVE_MS - (Date.now() - lastReturn));

    planAutoApproveTimerRef.current = setTimeout(() => {
      planAutoApproveTimerRef.current = null;
      const phasesNow = phasesRef.current;
      const planNow = phasesNow?.find((p) => p.phase === "plan");
      const runners = planNow?.planApproveRunners;
      if (!planNow || !runners) return;

      const pending = vendorsList.filter((v) => {
        if (planNow.approvedVendors.has(v)) return false;
        const d = planNow.cardData[v];
        const lp = d?.letter_plan;
        if (!lp || !String(lp).trim()) return false;
        return true;
      });

      void Promise.all(
        pending.map((v) => {
          const run = runners.get(v);
          if (!run) return Promise.resolve();
          return Promise.resolve(run()).catch((e) => console.warn("Plan auto-approve failed for", v, e));
        })
      );
    }, delay);
  }, [phaseUpdateTrigger, vendorsList]);

  const [inputClusterText, setInputClusterText] = useState({});
  const broadcastInputCluster = useCallback((clusterKey, text) => {
    if (!clusterKey) return;
    const t = String(text ?? "").trim();
    if (!t) return;
    setInputClusterText((prev) => ({ ...prev, [clusterKey]: text }));
  }, []);

  const [phaseCounters, setPhaseCounters] = useState({});

  const phasesRef = useRef(null);
  const vendorsListLengthRef = useRef(vendorsList.length);
  const phasesSchemaVersionRef = useRef(0);
  const includePlanStepRef = useRef(includePlanStep);
  const expandedDialogRef = useRef(null);

  if (
    !phasesRef.current ||
    vendorsListLengthRef.current !== vendorsList.length ||
    phasesSchemaVersionRef.current !== PHASE_FLOW_SCHEMA_VERSION ||
    includePlanStepRef.current !== includePlanStep
  ) {
    phasesRef.current = transformToPhaseStructure(vendorsList, setPhaseUpdateTrigger, phaseCounters, setPhaseCounters, includePlanStep);
    includePlanStepRef.current = includePlanStep;
    vendorsListLengthRef.current = vendorsList.length;
    phasesSchemaVersionRef.current = PHASE_FLOW_SCHEMA_VERSION;

    if (onRegisterPhases) {
      setTimeout(() => onRegisterPhases(phasesRef.current), 0);
    }
  }

  const phases = phasesRef.current;

  useEffect(() => {
    if (phasesRef.current) {
      phasesRef.current.forEach(phaseObj => {
        const phaseName = phaseObj.phase;
        const counters = phaseCounters[phaseName];
        if (counters) {
          phaseObj.readyCount = counters.readyCount;
          phaseObj.pendingCount = counters.pendingCount;
        }
      });
    }
  }, [phaseCounters]);

  const expandedPhase = expandedCard ? phases.find((p) => p.phase === expandedCard.phase) : null;
  const vendorIdx = expandedCard ? vendorsList.indexOf(expandedCard.vendor) : -1;
  const isFirstVendor = vendorIdx <= 0;
  const isLastVendor = vendorIdx >= vendorsList.length - 1;
  const nextPhase = expandedPhase?.next ?? null;
  const hasNextPhase = !!nextPhase;

  const goLeft = useCallback(() => {
    if (!expandedCard || isFirstVendor) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx <= 0) return;
    setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx - 1] });
  }, [expandedCard, vendorsList, isFirstVendor]);

  const goRight = useCallback(() => {
    if (!expandedCard) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx < 0) return;
    if (idx < vendorsList.length - 1) {
      setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx + 1] });
      return;
    }
    if (nextPhase) {
      setExpandedCard({ phase: nextPhase.phase, vendor: vendorsList[0] });
    }
  }, [expandedCard, vendorsList, nextPhase]);

  const onAfterApproveInExpanded = useCallback(() => {
    if (!expandedCard) return;
    const idx = vendorsList.indexOf(expandedCard.vendor);
    if (idx < 0) return;
    if (idx < vendorsList.length - 1) {
      setExpandedCard({ phase: expandedCard.phase, vendor: vendorsList[idx + 1] });
      return;
    }
    if (nextPhase) {
      setExpandedCard({ phase: nextPhase.phase, vendor: vendorsList[0] });
    }
  }, [expandedCard, vendorsList, nextPhase]);

  useEffect(() => {
    if (!expandedCard) return;
    const handler = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      const ce = e.target?.getAttribute?.("contenteditable") === "true";
      if (tag === "input" || tag === "textarea" || tag === "select" || ce) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goLeft();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        goRight();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [expandedCard, goLeft, goRight]);

  useEffect(() => {
    if (!expandedCard) return;
    const frame = requestAnimationFrame(() => {
      expandedDialogRef.current?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [expandedCard]);

  const saveFeedbackOverride = useCallback((vendor, key, val) => {
    if (!vendor || !key) return;
    if (onEditChange) {
      onEditChange(vendor, "draft", "feedback_overrides", { [key]: val });
    }
  }, [onEditChange]);

  const memoizedRenderVendors = useMemo(() => {
    const renderFunctions = new Map();
    phases.forEach(phaseObj => {
      const phaseName = phaseObj.phase;
      const phaseModule = phaseModules[phaseName];
      renderFunctions.set(phaseName, (vendor, overlayMode = false) => (
        <VendorCardWrapper
          key={`${phaseName}-${vendor}-wrapper${overlayMode ? "-overlay" : ""}`}
          phaseName={phaseName}
          vendor={vendor}
          phaseObj={phaseObj}
          phaseModule={phaseModule}
          sessionId={sessionId}
          documentId={documentId}
          draftFeedbackRegistryRef={draftFeedbackRegistryRef}
          onEditChange={onEditChange}
          onApprove={onApprove}
          onSaveFeedbackOverride={saveFeedbackOverride}
          onPhaseComplete={onPhaseComplete}
          triggerUpdate={() => setPhaseUpdateTrigger(prev => prev + 1)}
          onExpand={overlayMode ? undefined : () => toggleExpand(phaseName, vendor)}
          isExpanded={overlayMode}
          onCloseExpand={overlayMode ? closeExpand : undefined}
          useOverlayWidth={overlayMode}
          onAfterApproveInExpanded={overlayMode ? onAfterApproveInExpanded : undefined}
          inputClusterText={inputClusterText}
          broadcastInputCluster={broadcastInputCluster}
          onRetryPhaseFetch={onRetryPhaseFetch}
          onClearPhaseFetchError={onClearPhaseFetchError}
        />
      ));
    });
    return renderFunctions;
  }, [phases, sessionId, documentId, draftFeedbackRegistryRef, onEditChange, onApprove, onPhaseComplete, saveFeedbackOverride, toggleExpand, closeExpand, onAfterApproveInExpanded, inputClusterText, broadcastInputCluster, onRetryPhaseFetch, onClearPhaseFetchError]);

  phases.forEach(phaseObj => {
    const phaseName = phaseObj.phase;
    const phaseModule = phaseModules[phaseName];
    const title = phaseModule?.getPhaseTitle() || phaseName;

    let visible = true;
    if (phaseObj.previous) {
      visible = (phaseObj.previous.approvedVendors?.size ?? 0) > 0;
    }

    phaseObj.title = title;
    phaseObj.visible = visible;
    phaseObj.collapsed = collapsedPhases[phaseName] || false;
    phaseObj.toggle = () => setCollapsedPhases((prev) => ({ ...prev, [phaseName]: !prev[phaseName] }));
    phaseObj.renderVendor = memoizedRenderVendors.get(phaseName);
  });

  return (
    <>
      {expandedCard && expandedPhase && createPortal(
        <div
          role="presentation"
          onClick={closeExpand}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            padding: 24,
            boxSizing: "border-box",
            background: "rgba(0,0,0,0.2)",
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
          }}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); goLeft(); }}
            disabled={isFirstVendor}
            title="Previous (←)"
            style={{
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(0,0,0,0.25)",
              color: "rgba(255,255,255,0.9)",
              border: "none",
              cursor: isFirstVendor ? "not-allowed" : "pointer",
              opacity: isFirstVendor ? 0.4 : 1,
              fontSize: "22px",
            }}
          >
            ‹
          </button>
          <div
            ref={expandedDialogRef}
            role="dialog"
            aria-label={`Expanded: ${expandedCard.vendor}`}
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            style={{
              flex: "1 1 0",
              minWidth: 0,
              maxWidth: 1200,
              height: "85vh",
              maxHeight: "85vh",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              background: "var(--card-bg)",
              border: "1px solid var(--border-color)",
              borderRadius: 8,
              boxShadow: "0 12px 40px rgba(0,0,0,0.15)",
              outline: "none",
            }}
          >
            {expandedPhase.renderVendor(expandedCard.vendor, true)}
          </div>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); goRight(); }}
            disabled={isLastVendor && !hasNextPhase}
            title="Next (→)"
            style={{
              flexShrink: 0,
              width: 44,
              height: 44,
              borderRadius: "50%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(0,0,0,0.25)",
              color: "rgba(255,255,255,0.9)",
              border: "none",
              cursor: (isLastVendor && !hasNextPhase) ? "not-allowed" : "pointer",
              opacity: (isLastVendor && !hasNextPhase) ? 0.4 : 1,
              fontSize: "22px",
            }}
          >
            ›
          </button>
        </div>,
        document.body
      )}
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
      {phases.filter((phase) => phase.visible).map((phase) => (
        <PhaseSection
          key={phase.phase}
          title={phase.title}
          collapsed={phase.collapsed}
          onToggle={phase.toggle}
          showApproveAll={vendorsList.length > 0}
          approveAllDisabled={false}
          readyCount={phase.readyCount || 0}
          totalCount={phase.pendingCount || 0}
          onApproveAll={() => {
            if (onApproveAll) {
              onApproveAll(phase.phase);
            }

            vendorsList.forEach(vendor => {
              if (phase.approvedVendors) {
                phase.approvedVendors.add(vendor);
              }
            });

            setPhaseUpdateTrigger(prev => prev + 1);
          }}
        >
          {vendorsList
            .filter((v) => !(expandedCard?.phase === phase.phase && expandedCard?.vendor === v))
            .map((vendor) => phase.renderVendor(vendor))}
        </PhaseSection>
      ))}
      </div>
    </>
  );
}
