import React, { useState, useEffect, useCallback } from 'react';
import { fetchWithHeartbeat } from '../utils/apiHelpers';
import InstructionMergePanel from './InstructionMergePanel';
import { hasUpstreamUpdate } from '../utils/instructionMerge';

const TABS = [
  { key: 'style', label: 'Draft Style', endpoint: '/api/style-instructions/', description: 'Tone, wording, and formatting for the generated cover letter (not the strategic plan).' },
  { key: 'structure', label: 'Letter plan', endpoint: '/api/structure-instructions/', description: 'How the AI outlines strengths, weaknesses, and letter structure (~10 telegraphic lines, no draft prose).' },
  { key: 'search', label: 'Background Search', endpoint: '/api/search-instructions/', description: 'These instructions guide how the AI researches companies during the background phase.' },
];

const REVERT_LABEL = 'Remove custom instructions and go back to default';

const DANGER_REVERT_STYLE = {
  padding: '10px 20px',
  border: '1px solid #dc2626',
  borderRadius: '4px',
  backgroundColor: '#dc2626',
  color: '#fff',
  cursor: 'pointer',
  fontWeight: 600,
};

const EMPTY_TAB = {
  instructions: '',
  savedInstructions: '',
  meta: null,
  loading: false,
  saving: false,
  clearing: false,
  error: null,
  saveSuccess: false,
};

const StyleInstructionsBlade = ({ isOpen, onClose, onUpstreamStatusChange }) => {
  const [activeTab, setActiveTab] = useState('style');
  const [tabState, setTabState] = useState({
    style: { ...EMPTY_TAB },
    structure: { ...EMPTY_TAB },
    search: { ...EMPTY_TAB },
  });

  const updateTab = (tabKey, updates) => {
    setTabState((prev) => ({
      ...prev,
      [tabKey]: { ...prev[tabKey], ...updates },
    }));
  };

  const applyPayload = (tabKey, data) => {
    updateTab(tabKey, {
      instructions: data.instructions ?? '',
      savedInstructions: data.instructions ?? '',
      meta: data,
      loading: false,
      error: null,
    });
  };

  const notifyUpstream = useCallback((state) => {
    if (!onUpstreamStatusChange) return;
    const any = TABS.some((t) => hasUpstreamUpdate(state[t.key]?.meta));
    onUpstreamStatusChange(any);
  }, [onUpstreamStatusChange]);

  const loadInstructions = async (tabKey, { force = false } = {}) => {
    const tab = TABS.find((t) => t.key === tabKey);
    if (!tab) return;
    if (!force && tabState[tabKey].meta && !tabState[tabKey].error) return;

    updateTab(tabKey, { loading: true, error: null });
    try {
      const { data } = await fetchWithHeartbeat(tab.endpoint);
      applyPayload(tabKey, data);
      setTabState((prev) => {
        const next = {
          ...prev,
          [tabKey]: {
            ...prev[tabKey],
            instructions: data.instructions ?? '',
            savedInstructions: data.instructions ?? '',
            meta: data,
            loading: false,
            error: null,
          },
        };
        notifyUpstream(next);
        return next;
      });
    } catch (err) {
      updateTab(tabKey, { error: err.message, loading: false });
    }
  };

  useEffect(() => {
    if (isOpen) {
      TABS.forEach((tab) => loadInstructions(tab.key, { force: true }));
    }
  }, [isOpen]);

  const saveInstructions = async (tabKey) => {
    const tab = TABS.find((t) => t.key === tabKey);
    if (!tab) return;

    updateTab(tabKey, { saving: true, error: null, saveSuccess: false });
    try {
      const { data } = await fetchWithHeartbeat(tab.endpoint, {
        method: 'POST',
        body: JSON.stringify({ instructions: tabState[tabKey].instructions }),
      });
      setTabState((prev) => {
        const next = {
          ...prev,
          [tabKey]: {
            ...prev[tabKey],
            instructions: data.instructions ?? prev[tabKey].instructions,
            savedInstructions: data.instructions ?? prev[tabKey].instructions,
            meta: data,
            saving: false,
            saveSuccess: true,
          },
        };
        notifyUpstream(next);
        return next;
      });
      setTimeout(() => updateTab(tabKey, { saveSuccess: false }), 3000);
    } catch (err) {
      updateTab(tabKey, { error: err.message, saving: false });
    }
  };

  const revertToDefault = async (tabKey) => {
    const tab = TABS.find((t) => t.key === tabKey);
    if (!tab) return;
    if (!window.confirm(`${REVERT_LABEL}? Your saved custom text will be deleted permanently.`)) return;

    updateTab(tabKey, { clearing: true, error: null });
    try {
      const { data } = await fetchWithHeartbeat(tab.endpoint, { method: 'DELETE' });
      setTabState((prev) => {
        const next = {
          ...prev,
          [tabKey]: {
            ...prev[tabKey],
            instructions: data.instructions ?? '',
            savedInstructions: data.instructions ?? '',
            meta: data,
            clearing: false,
            saveSuccess: false,
          },
        };
        notifyUpstream(next);
        return next;
      });
    } catch (err) {
      updateTab(tabKey, { error: err.message, clearing: false });
    }
  };

  const current = tabState[activeTab];
  const hasChanges = current.instructions !== current.savedInstructions;
  const currentTabMeta = TABS.find((t) => t.key === activeTab);
  const upstreamTabs = TABS.filter((t) => hasUpstreamUpdate(tabState[t.key].meta));

  const handleClose = () => {
    const unsavedTabs = TABS.filter((t) => tabState[t.key].instructions !== tabState[t.key].savedInstructions);
    if (unsavedTabs.length > 0) {
      if (window.confirm('You have unsaved changes. Are you sure you want to close?')) {
        const reverted = { ...tabState };
        unsavedTabs.forEach((t) => {
          reverted[t.key] = { ...reverted[t.key], instructions: reverted[t.key].savedInstructions };
        });
        setTabState(reverted);
        onClose();
      }
    } else {
      onClose();
    }
  };

  const resetToSaved = () => {
    updateTab(activeTab, { instructions: current.savedInstructions });
  };

  if (!isOpen) return null;

  return (
    <>
      <div onClick={handleClose} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.3)', zIndex: 999 }} aria-hidden="true" />
      <div style={{
        position: 'fixed',
        top: '5%',
        left: '5%',
        right: '5%',
        bottom: '5%',
        width: '90%',
        height: '90%',
        margin: 'auto',
        backgroundColor: 'var(--bg-color)',
        boxShadow: '0 4px 24px rgba(0,0,0,0.2)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid var(--border-color)',
        borderRadius: '8px',
        color: 'var(--text-color)',
      }}>
        <div style={{
          padding: '20px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'var(--header-bg)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <h2 style={{ margin: 0, fontSize: '1.5em', color: 'var(--text-color)' }}>
            AI Instructions
          </h2>
          <button
            onClick={handleClose}
            type="button"
            style={{
              background: 'none',
              border: 'none',
              fontSize: '1.5em',
              cursor: 'pointer',
              color: 'var(--secondary-text-color)',
              padding: '5px',
            }}
          >
            &times;
          </button>
        </div>

        {upstreamTabs.length > 0 && (
          <div style={{
            padding: '10px 20px',
            background: 'rgba(99, 102, 241, 0.12)',
            borderBottom: '1px solid rgba(99, 102, 241, 0.35)',
            color: 'var(--text-color)',
            fontSize: 13,
          }}>
            Default instructions updated for: {upstreamTabs.map((t) => t.label).join(', ')}.
            Open those tabs to review and merge.
          </div>
        )}

        <div style={{
          display: 'flex',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'var(--header-bg)',
          padding: '0 20px',
        }}>
          {TABS.map((tab) => {
            const isActive = activeTab === tab.key;
            const tabHasChanges = tabState[tab.key].instructions !== tabState[tab.key].savedInstructions;
            const tabUpstream = hasUpstreamUpdate(tabState[tab.key].meta);
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                type="button"
                style={{
                  padding: '10px 20px',
                  border: 'none',
                  borderBottom: isActive ? '3px solid #007bff' : '3px solid transparent',
                  backgroundColor: 'transparent',
                  color: isActive ? '#007bff' : 'var(--secondary-text-color)',
                  cursor: 'pointer',
                  fontSize: '14px',
                  fontWeight: isActive ? 'bold' : 'normal',
                  position: 'relative',
                }}
              >
                {tab.label}
                {tabUpstream && (
                  <span style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: '#6366f1',
                    marginLeft: '6px',
                    verticalAlign: 'middle',
                  }} title="Default instructions updated" />
                )}
                {tabHasChanges && (
                  <span style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: '#f59e0b',
                    marginLeft: '6px',
                    verticalAlign: 'middle',
                  }} title="Unsaved changes" />
                )}
              </button>
            );
          })}
        </div>

        <div style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
          {current.loading && (
            <div style={{ textAlign: 'center', padding: '20px', color: 'var(--secondary-text-color)' }}>
              Loading {currentTabMeta.label.toLowerCase()} instructions...
            </div>
          )}

          {current.error && (
            <div style={{
              backgroundColor: 'var(--error-bg)',
              border: '1px solid var(--error-border)',
              borderRadius: '4px',
              padding: '10px',
              marginBottom: '15px',
              color: 'var(--error-text)',
            }}>
              Error: {current.error}
            </div>
          )}

          {current.saveSuccess && (
            <div style={{
              backgroundColor: 'var(--success-bg, #efe)',
              border: '1px solid var(--success-border, #cfc)',
              borderRadius: '4px',
              padding: '10px',
              marginBottom: '15px',
              color: 'var(--success-text, #3c3)',
            }}>
              {currentTabMeta.label} instructions saved successfully!
            </div>
          )}

          {!current.loading && (
            <>
              <div style={{ marginBottom: '15px' }}>
                <p style={{ margin: '0 0 10px 0', color: 'var(--secondary-text-color)' }}>
                  {currentTabMeta.description}
                  {current.meta?.is_custom ? ' Using your custom version.' : ' Using repo default.'}
                </p>
              </div>

              {current.meta?.is_custom && (
                <InstructionMergePanel
                  meta={current.meta}
                  draftText={current.instructions}
                  onApplyDraft={(text) => updateTab(activeTab, { instructions: text })}
                  onRevertToDefault={() => revertToDefault(activeTab)}
                  busy={current.saving || current.clearing}
                />
              )}

              <textarea
                value={current.instructions}
                onChange={(e) => updateTab(activeTab, { instructions: e.target.value })}
                style={{
                  flex: 1,
                  minHeight: 240,
                  width: '100%',
                  padding: '15px',
                  border: '1px solid var(--border-color)',
                  borderRadius: '4px',
                  fontSize: '14px',
                  fontFamily: 'monospace',
                  lineHeight: '1.5',
                  resize: 'vertical',
                  outline: 'none',
                  backgroundColor: 'var(--input-bg)',
                  color: 'var(--text-color)',
                }}
                placeholder={`Enter ${currentTabMeta.label.toLowerCase()} instructions...`}
              />

              <div style={{
                marginTop: '20px',
                display: 'flex',
                gap: '10px',
                justifyContent: 'flex-end',
                flexWrap: 'wrap',
                alignItems: 'center',
              }}>
                {current.meta?.is_custom && (
                  <button
                    type="button"
                    onClick={() => revertToDefault(activeTab)}
                    disabled={current.clearing || current.saving}
                    title="Permanently deletes your saved custom instructions"
                    style={{
                      ...DANGER_REVERT_STYLE,
                      marginRight: 'auto',
                      cursor: current.clearing || current.saving ? 'not-allowed' : 'pointer',
                      opacity: current.clearing || current.saving ? 0.65 : 1,
                    }}
                  >
                    {current.clearing ? 'Removing…' : REVERT_LABEL}
                  </button>
                )}
                {hasChanges && (
                  <button
                    type="button"
                    onClick={resetToSaved}
                    style={{
                      padding: '10px 20px',
                      border: '1px solid var(--border-color)',
                      borderRadius: '4px',
                      backgroundColor: 'var(--button-bg)',
                      color: 'var(--button-text)',
                      cursor: 'pointer',
                    }}
                  >
                    Reset
                  </button>
                )}

                <button
                  type="button"
                  onClick={() => saveInstructions(activeTab)}
                  disabled={current.saving || !hasChanges || !current.instructions.trim()}
                  style={{
                    padding: '10px 20px',
                    border: 'none',
                    borderRadius: '4px',
                    backgroundColor: hasChanges && current.instructions.trim() ? '#007bff' : 'var(--header-bg)',
                    color: 'white',
                    cursor: hasChanges && current.instructions.trim() ? 'pointer' : 'not-allowed',
                    fontWeight: 'bold',
                  }}
                >
                  {current.saving ? 'Saving...' : current.meta?.is_custom ? 'Save changes' : 'Save as custom'}
                </button>
              </div>

              {hasChanges && (
                <div style={{
                  marginTop: '10px',
                  fontSize: '12px',
                  color: 'var(--secondary-text-color)',
                  fontStyle: 'italic',
                }}>
                  * Changes will apply to future letter generations
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
};

export default StyleInstructionsBlade;
