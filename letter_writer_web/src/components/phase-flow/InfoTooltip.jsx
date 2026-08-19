import React, { useState, useEffect, useRef } from "react";

export default function InfoTooltip({ text, children }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipRef = useRef(null);

  useEffect(() => {
    if (showTooltip && tooltipRef.current) {
      const handleMouseLeave = () => setShowTooltip(false);
      const element = tooltipRef.current;
      element.addEventListener('mouseleave', handleMouseLeave);
      return () => element.removeEventListener('mouseleave', handleMouseLeave);
    }
  }, [showTooltip]);

  return (
    <span
      ref={tooltipRef}
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {children}
      {showTooltip && text && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '4px',
            padding: '6px 10px',
            backgroundColor: 'var(--bg-color)',
            color: 'var(--text-color)',
            border: '1px solid var(--border-color)',
            borderRadius: '4px',
            fontSize: '12px',
            zIndex: 1000,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            maxWidth: '250px',
            whiteSpace: 'normal',
            textAlign: 'left',
          }}
        >
          {text}
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid var(--bg-color)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '7px solid transparent',
              borderRight: '7px solid transparent',
              borderTop: '7px solid var(--border-color)',
              zIndex: -1,
            }}
          />
        </div>
      )}
    </span>
  );
}
