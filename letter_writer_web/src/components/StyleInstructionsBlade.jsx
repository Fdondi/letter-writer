import React, { useState, useEffect } from 'react';
import { fetchWithHeartbeat } from '../utils/apiHelpers';

const TABS = [
  { key: 'style', label: 'Draft Style', endpoint: '/api/style-instructions/', description: 'These instructions guide the writing style and tone when generating cover letters.' },
  { key: 'search', label: 'Background Search', endpoint: '/api/search-instructions/', description: 'These instructions guide how the AI researches companies during the background phase.' },
];

const StyleInstructionsBlade = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState('style');
  // Per-tab state
  const [tabState, setTabState] = useState({
    style: { instructions: '', original: '', loading: false, saving: false, error: null, saveSuccess: false },
    search: { instructions: '', original: '', loading: false, saving: false, error: null, saveSuccess: false },
  });

  // Load instructions when blade opens or tab changes
  useEffect(() => {
    if (isOpen) {
      loadInstructions(activeTab);
    }
  }, [isOpen, activeTab]);

  const updateTab = (tabKey, updates) => {
    setTabState(prev => ({
      ...prev,
      [tabKey]: { ...prev[tabKey], ...updates }
    }));
  };

  const loadInstructions = async (tabKey) => {
    const tab = TABS.find(t => t.key === tabKey);
    if (!tab) return;
    // Don't reload if already loaded
    if (tabState[tabKey].original && !tabState[tabKey].error) return;
    
    updateTab(tabKey, { loading: true, error: null });
    try {
      const { data } = await fetchWithHeartbeat(tab.endpoint);
      updateTab(tabKey, { instructions: data.instructions, original: data.instructions, loading: false });
    } catch (err) {
      updateTab(tabKey, { error: err.message, loading: false });
    }
  };

  const saveInstructions = async (tabKey) => {
    const tab = TABS.find(t => t.key === tabKey);
    if (!tab) return;
    
    updateTab(tabKey, { saving: true, error: null, saveSuccess: false });
    try {
      await fetchWithHeartbeat(tab.endpoint, {
        method: 'POST',
        body: JSON.stringify({ instructions: tabState[tabKey].instructions }),
      });
      
      updateTab(tabKey, { original: tabState[tabKey].instructions, saveSuccess: true, saving: false });
      setTimeout(() => updateTab(tabKey, { saveSuccess: false }), 3000);
    } catch (err) {
      updateTab(tabKey, { error: err.message, saving: false });
    }
  };

  const current = tabState[activeTab];
  const hasChanges = current.instructions !== current.original;
  const currentTabMeta = TABS.find(t => t.key === activeTab);

  const handleClose = () => {
    // Check for unsaved changes in any tab
    const unsavedTabs = TABS.filter(t => tabState[t.key].instructions !== tabState[t.key].original);
    if (unsavedTabs.length > 0) {
      if (window.confirm('You have unsaved changes. Are you sure you want to close?')) {
        // Revert all unsaved changes
        const reverted = { ...tabState };
        unsavedTabs.forEach(t => {
          reverted[t.key] = { ...reverted[t.key], instructions: reverted[t.key].original };
        });
        setTabState(reverted);
        onClose();
      }
    } else {
      onClose();
    }
  };

  const resetToOriginal = () => {
    updateTab(activeTab, { instructions: current.original });
  };

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      right: 0,
      width: '50%',
      height: '100vh',
      backgroundColor: 'var(--bg-color)',
      boxShadow: '-4px 0 8px rgba(0,0,0,0.1)',
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      borderLeft: '1px solid var(--border-color)',
      color: 'var(--text-color)'
    }}>
      {/* Header */}
      <div style={{
        padding: '20px',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--header-bg)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <h2 style={{ margin: 0, fontSize: '1.5em', color: 'var(--text-color)' }}>
          AI Instructions
        </h2>
        <button
          onClick={handleClose}
          style={{
            background: 'none',
            border: 'none',
            fontSize: '1.5em',
            cursor: 'pointer',
            color: 'var(--secondary-text-color)',
            padding: '5px'
          }}
        >
          &times;
        </button>
      </div>

      {/* Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--header-bg)',
        padding: '0 20px',
      }}>
        {TABS.map(tab => {
          const isActive = activeTab === tab.key;
          const tabHasChanges = tabState[tab.key].instructions !== tabState[tab.key].original;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
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

      {/* Content */}
      <div style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column' }}>
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
            color: 'var(--error-text)'
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
            color: 'var(--success-text, #3c3)'
          }}>
            {currentTabMeta.label} instructions saved successfully!
          </div>
        )}

        {!current.loading && (
          <>
            <div style={{ marginBottom: '15px' }}>
              <p style={{ margin: '0 0 10px 0', color: 'var(--secondary-text-color)' }}>
                {currentTabMeta.description}
              </p>
            </div>

            <textarea
              value={current.instructions}
              onChange={(e) => updateTab(activeTab, { instructions: e.target.value })}
              style={{
                flex: 1,
                width: '100%',
                padding: '15px',
                border: '1px solid var(--border-color)',
                borderRadius: '4px',
                fontSize: '14px',
                fontFamily: 'monospace',
                lineHeight: '1.5',
                resize: 'none',
                outline: 'none',
                backgroundColor: 'var(--input-bg)',
                color: 'var(--text-color)'
              }}
              placeholder={`Enter ${currentTabMeta.label.toLowerCase()} instructions...`}
            />

            {/* Action buttons */}
            <div style={{
              marginTop: '20px',
              display: 'flex',
              gap: '10px',
              justifyContent: 'flex-end'
            }}>
              {hasChanges && (
                <button
                  onClick={resetToOriginal}
                  style={{
                    padding: '10px 20px',
                    border: '1px solid var(--border-color)',
                    borderRadius: '4px',
                    backgroundColor: 'var(--button-bg)',
                    color: 'var(--button-text)',
                    cursor: 'pointer'
                  }}
                >
                  Reset
                </button>
              )}
              
              <button
                onClick={() => saveInstructions(activeTab)}
                disabled={current.saving || !hasChanges || !current.instructions.trim()}
                style={{
                  padding: '10px 20px',
                  border: 'none',
                  borderRadius: '4px',
                  backgroundColor: hasChanges && current.instructions.trim() ? '#007bff' : 'var(--header-bg)',
                  color: 'white',
                  cursor: hasChanges && current.instructions.trim() ? 'pointer' : 'not-allowed',
                  fontWeight: 'bold'
                }}
              >
                {current.saving ? 'Saving...' : 'Save Changes'}
              </button>
            </div>

            {hasChanges && (
              <div style={{
                marginTop: '10px',
                fontSize: '12px',
                color: 'var(--secondary-text-color)',
                fontStyle: 'italic'
              }}>
                * Changes will apply to future letter generations
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default StyleInstructionsBlade;
