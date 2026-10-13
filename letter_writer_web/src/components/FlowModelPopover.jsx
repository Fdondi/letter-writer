import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import VendorFlowModelSettings from "./VendorFlowModelSettings";
import {
  ensureFlowModelsLoaded,
  getFlowModelState,
  subscribeFlowModels,
  updateExtractionVendor,
  updateFlowRole,
} from "./flowModelStore";

/**
 * Model picker for one flow, opened from the button that runs that flow.
 */
function placePopover(buttonEl, align) {
  const rect = buttonEl.getBoundingClientRect();
  const margin = 8;
  const gap = 6;
  const width = Math.min(560, window.innerWidth - margin * 2);
  let left = align === "end" ? rect.right - width : rect.left;
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
  const spaceBelow = window.innerHeight - rect.bottom - gap - margin;
  const spaceAbove = rect.top - gap - margin;
  const openUp = spaceBelow < 220 && spaceAbove > spaceBelow;
  return {
    left,
    width,
    maxHeight: Math.max(120, openUp ? spaceAbove : spaceBelow),
    top: openUp ? undefined : rect.bottom + gap,
    bottom: openUp ? window.innerHeight - rect.top + gap : undefined,
  };
}

export default function FlowModelPopover({
  flowId,
  ariaLabel,
  vendors = null,
  align = "start",
  testId,
}) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState(getFlowModelState);
  const [position, setPosition] = useState(null);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const dialogRef = useRef(null);

  useEffect(() => subscribeFlowModels(() => setSnapshot(getFlowModelState())), []);

  useEffect(() => {
    ensureFlowModelsLoaded();
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return undefined;
    }
    const update = () => {
      if (buttonRef.current) setPosition(placePopover(buttonRef.current, align));
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => {
      const target = event.target;
      if (rootRef.current?.contains(target) || dialogRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const vendorKeys = Array.isArray(vendors) ? vendors : null;

  return (
    <div ref={rootRef} style={{ position: "relative", flexShrink: 0 }}>
      <button
        ref={buttonRef}
        type="button"
        data-testid={testId}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((prev) => !prev)}
        style={{
          padding: "10px 12px",
          background: "transparent",
          color: "var(--text-color)",
          border: "1px solid var(--border-color)",
          borderRadius: 4,
          cursor: "pointer",
          fontSize: 13,
        }}
      >
        Models
      </button>
      {open && position
        ? createPortal(
          <div
            ref={dialogRef}
            role="dialog"
            aria-label={ariaLabel}
            style={{
              position: "fixed",
              zIndex: 80,
              top: position.top,
              bottom: position.bottom,
              left: position.left,
              width: position.width,
              maxHeight: position.maxHeight,
              overflow: "auto",
              background: "var(--bg-color)",
              border: "1px solid var(--border-color)",
              borderRadius: 8,
              padding: 14,
              boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
              pointerEvents: "auto",
            }}
          >
            {snapshot.error && snapshot.flows.length === 0 ? (
              <p style={{ margin: "0 0 8px", fontSize: 12, color: "var(--error-text)" }}>{snapshot.error}</p>
            ) : null}
            <VendorFlowModelSettings
              embeddedFlowId={flowId}
              flows={snapshot.flows}
              vendorRoleModels={snapshot.vendorRoleModels}
              onVendorRoleModelsChange={(updater) => {
                const next = typeof updater === "function" ? updater(snapshot.vendorRoleModels) : updater;
                const prev = snapshot.vendorRoleModels || {};
                Object.keys(next || {}).forEach((vendor) => {
                  const roles = next[vendor] || {};
                  Object.keys(roles).forEach((role) => {
                    if (roles[role] !== (prev[vendor] || {})[role]) {
                      updateFlowRole(vendor, role, roles[role]);
                    }
                  });
                });
              }}
              grouped={snapshot.grouped}
              vendorKeys={vendorKeys}
              extractionVendor={snapshot.extractionVendor}
              onExtractionVendorChange={flowId === "initial" ? updateExtractionVendor : null}
              hideSaveButton
              saving={snapshot.saving}
              saveError={snapshot.error}
            />
          </div>,
          document.body,
        )
        : null}
    </div>
  );
}
