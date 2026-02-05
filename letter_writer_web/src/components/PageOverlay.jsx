import React, { useEffect } from 'react';

/**
 * A full-page overlay component for rendering pages without unmounting the main content.
 * Takes at least 90% of the page and makes it clear it's drawing over the main content.
 */
const PageOverlay = ({ isOpen, onClose, title, children }) => {
  // Handle Escape key to close
  useEffect(() => {
    if (!isOpen) return;
    
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <>
      {/* Semi-transparent backdrop */}
      <div
        onClick={onClose}
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
            {title}
          </h2>
          <button
            onClick={onClose}
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
        <div style={{ 
          flex: 1, 
          overflow: 'auto',
          backgroundColor: 'var(--bg-color)',
        }}>
          {children}
        </div>
      </div>
    </>
  );
};

export default PageOverlay;
