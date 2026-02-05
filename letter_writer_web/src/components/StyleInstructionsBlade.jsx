import React, { useState, useEffect } from 'react';
import { fetchWithHeartbeat } from '../utils/apiHelpers';

const StyleInstructionsBlade = ({ isOpen, onClose }) => {
  const [instructions, setInstructions] = useState('');
  const [originalInstructions, setOriginalInstructions] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Load instructions when blade opens
  useEffect(() => {
    if (isOpen) {
      loadInstructions();
    }
  }, [isOpen]);

  // Handle Escape key to close (with unsaved changes confirmation)
  useEffect(() => {
    if (!isOpen) return;
    
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        handleClose();
      }
    };
    
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, instructions, originalInstructions]);

  const loadInstructions = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await fetchWithHeartbeat('/api/style-instructions/');
      setInstructions(data.instructions);
      setOriginalInstructions(data.instructions);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const saveInstructions = async () => {
    setSaving(true);
    setError(null);
    setSaveSuccess(false);
    try {
      await fetchWithHeartbeat('/api/style-instructions/', {
        method: 'POST',
        body: JSON.stringify({ instructions }),
      });
      
      setOriginalInstructions(instructions);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = instructions !== originalInstructions;

  const handleClose = () => {
    if (hasChanges) {
      if (window.confirm('You have unsaved changes. Are you sure you want to close?')) {
        setInstructions(originalInstructions);
        onClose();
      }
    } else {
      onClose();
    }
  };

  const resetToOriginal = () => {
    setInstructions(originalInstructions);
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Semi-transparent backdrop */}
      <div
        onClick={handleClose}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          zIndex: 999,
        }}
      />
      
      {/* Main overlay panel */}
      <div style={{
        position: 'fixed',
        top: '2%',
        left: '2%',
        right: '2%',
        bottom: '2%',
        backgroundColor: 'var(--bg-color)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        borderRadius: '12px',
        border: '1px solid var(--border-color)',
        color: 'var(--text-color)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'var(--header-bg)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}>
          <h2 style={{ margin: 0, fontSize: '1.25em', color: 'var(--text-color)' }}>
            Style Instructions
          </h2>
          <button
            onClick={handleClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '1.5em',
              cursor: 'pointer',
              color: 'var(--secondary-text-color)',
              padding: '5px 10px',
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background-color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.target.style.backgroundColor = 'var(--panel-bg)';
            }}
            onMouseLeave={(e) => {
              e.target.style.backgroundColor = 'transparent';
            }}
            title="Close (Esc)"
          >
            ×
          </button>
        </div>

      {/* Content */}
      <div style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column' }}>
        {loading && (
          <div style={{ textAlign: 'center', padding: '20px', color: 'var(--secondary-text-color)' }}>
            Loading style instructions...
          </div>
        )}

        {error && (
          <div style={{
            backgroundColor: 'var(--error-bg)',
            border: '1px solid var(--error-border)',
            borderRadius: '4px',
            padding: '10px',
            marginBottom: '15px',
            color: 'var(--error-text)'
          }}>
            Error: {error}
          </div>
        )}

        {saveSuccess && (
          <div style={{
            backgroundColor: 'var(--success-bg, #efe)',
            border: '1px solid var(--success-border, #cfc)',
            borderRadius: '4px',
            padding: '10px',
            marginBottom: '15px',
            color: 'var(--success-text, #3c3)'
          }}>
            Style instructions saved successfully!
          </div>
        )}

        {!loading && (
          <>
            <div style={{ marginBottom: '15px' }}>
              <p style={{ margin: '0 0 10px 0', color: 'var(--secondary-text-color)' }}>
                These instructions will be used when generating cover letters. 
                Modify them to customize the writing style and approach.
              </p>
            </div>

            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
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
              placeholder="Enter style instructions..."
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
                onClick={saveInstructions}
                disabled={saving || !hasChanges || !instructions.trim()}
                style={{
                  padding: '10px 20px',
                  border: 'none',
                  borderRadius: '4px',
                  backgroundColor: hasChanges && instructions.trim() ? '#007bff' : 'var(--header-bg)',
                  color: 'white',
                  cursor: hasChanges && instructions.trim() ? 'pointer' : 'not-allowed',
                  fontWeight: 'bold'
                }}
              >
                {saving ? 'Saving...' : 'Save Changes'}
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
    </>
  );
};

export default StyleInstructionsBlade;
