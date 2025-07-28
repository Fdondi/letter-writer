import React, { useState, useRef } from "react";
import Paragraph, { ItemTypes } from "./Paragraph";
import LetterCard from "./LetterCard";
import { useDrop } from "react-dnd";
import { HoverProvider } from "../contexts/HoverContext";
import { v4 as uuidv4 } from "uuid";

export default function LetterTabs({ 
  vendorsList, 
  vendorParagraphs, 
  finalParagraphs, 
  setFinalParagraphs, 
  originalText, 
  failedVendors, 
  loadingVendors, 
  onRetry, 
  vendorColors, 
  onAddParagraph 
}) {
  const [collapsed, setCollapsed] = useState([]);
  const [finalLetter, setFinalLetter] = useState("");
  const [originalLetter, setOriginalLetter] = useState(originalText || "");
  const finalColumnRef = useRef(null);

  const toggleCollapse = (vendor) => {
    setCollapsed((prev) =>
      prev.includes(vendor) ? prev.filter((v) => v !== vendor) : [...prev, vendor]
    );
  };

  const vendorKeys = Object.keys(vendorParagraphs);
  const visibleVendors = vendorKeys.filter((v) => !collapsed.includes(v));
  const collapsedVendors = vendorKeys.filter((v) => collapsed.includes(v));
  const totalVisible = visibleVendors.length + 2; // +2 for final letter and original letter
  const columnWidth = totalVisible > 0 ? `${100 / totalVisible}%` : "100%";

  const moveFinalParagraph = (from, to) => {
    setFinalParagraphs((prev) => {
      if (from < 0 || from >= prev.length || to < 0 || to > prev.length) {
        console.warn('Invalid move indices:', { from, to, arrayLength: prev.length });
        return prev; // Return unchanged if indices are invalid
      }
      const copy = [...prev];
      const [moved] = copy.splice(from, 1);
      copy.splice(to, 0, moved);
      return copy;
    });
  };

  const handleFragmentSplit = (paragraphIndex, fragments, originalText, newText) => {
    setFinalParagraphs((prev) => {
      const copy = [...prev];
      const originalParagraph = copy[paragraphIndex];
      
      // Create fragments for the parts that match original text
      const processedFragments = [];
      let remainingText = newText;
      
      fragments.forEach(fragment => {
        if (originalText.includes(fragment.text.trim())) {
          // This is original AI text - keep the vendor connection
          processedFragments.push({
            ...fragment,
            vendor: originalParagraph.vendor,
            sourceId: originalParagraph.sourceId || originalParagraph.id
          });
        } else {
          // This is new user text - make it unconnected (white)
          processedFragments.push({
            ...fragment,
            vendor: null, // No vendor means white background
            sourceId: null,
            isUserText: true
          });
        }
      });
      
      copy.splice(paragraphIndex, 1, ...processedFragments);
      return copy;
    });
  };

  const addParagraphAtPosition = (paragraph, targetIndex = null) => {
    const newParagraph = {
      ...paragraph,
      id: uuidv4(), // Give it a new ID for the final column
      sourceId: paragraph.sourceId || paragraph.id, // Track original source
      vendor: paragraph.vendor || null // Ensure vendor is never undefined
    };

    setFinalParagraphs((prev) => {
      if (targetIndex !== null) {
        const copy = [...prev];
        copy.splice(targetIndex, 0, newParagraph);
        return copy;
      }
      return [...prev, newParagraph];
    });
  };

  const addNewParagraph = (index) => {
    const newParagraph = {
      id: uuidv4(),
      text: "",
      vendor: null, // No vendor = white background
      sourceId: null,
      isUserText: true
    };
    
    setFinalParagraphs((prev) => {
      const copy = [...prev];
      copy.splice(index, 0, newParagraph);
      return copy;
    });
  };

  const deleteParagraph = (index) => {
    setFinalParagraphs((prev) => {
      const copy = [...prev];
      copy.splice(index, 1);
      return copy;
    });
  };

  const updateParagraphText = (index, newText) => {
    setFinalParagraphs((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], text: newText };
      return copy;
    });
  };

  const copyFinalText = () => {
    const fullText = finalParagraphs.map(p => p.text).join('\n\n');
    navigator.clipboard.writeText(fullText).then(() => {
      // Simple visual feedback
      const button = document.getElementById('copy-final-text-btn');
      const originalText = button.textContent;
      button.textContent = '✓ Copied!';
      button.style.background = '#10b981';
      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = '#3b82f6';
      }, 2000);
    }).catch(err => {
      console.error('Failed to copy text:', err);
      alert('Failed to copy text to clipboard');
    });
  };

  // Drop zone for the final column
  const [{ isOver }, drop] = useDrop({
    accept: ItemTypes.PARAGRAPH,
    drop(item, monitor) {
      if (monitor.didDrop()) return;
      
      // Calculate drop position based on mouse position
      const finalColumnRect = finalColumnRef.current?.getBoundingClientRect();
      const clientOffset = monitor.getClientOffset();
      
      if (finalColumnRect && clientOffset) {
        const relativeY = clientOffset.y - finalColumnRect.top;
        const headerHeight = 40; // Approximate height of the header
        const adjustedY = relativeY - headerHeight;
        
        if (adjustedY > 0) {
          // Find the best insertion point
          const paragraphElements = finalColumnRef.current.querySelectorAll('[data-paragraph-index]');
          let targetIndex = finalParagraphs.length;
          
          for (let i = 0; i < paragraphElements.length; i++) {
            const rect = paragraphElements[i].getBoundingClientRect();
            const elementY = rect.top - finalColumnRect.top - headerHeight;
            const elementMiddle = elementY + (rect.height / 2);
            
            if (adjustedY < elementMiddle) {
              targetIndex = i;
              break;
            }
          }
          
          addParagraphAtPosition(item.paragraph, targetIndex);
        } else {
          addParagraphAtPosition(item.paragraph, 0);
        }
      } else {
        addParagraphAtPosition(item.paragraph);
      }
    },
    collect: (monitor) => ({
      isOver: monitor.isOver({ shallow: true })
    })
  });

  const PlusButton = ({ onClick, style = {} }) => (
    <div
      onClick={onClick}
      style={{
        padding: "4px 8px",
        margin: "2px 0",
        textAlign: "center",
        cursor: "pointer",
        color: "#666",
        border: "1px dashed #ccc",
        borderRadius: 4,
        background: "#f9f9f9",
        fontSize: "12px",
        transition: "all 0.2s ease",
        ...style
      }}
      onMouseEnter={(e) => {
        e.target.style.background = "#e0e0e0";
        e.target.style.borderColor = "#999";
      }}
      onMouseLeave={(e) => {
        e.target.style.background = "#f9f9f9";
        e.target.style.borderColor = "#ccc";
      }}
    >
      + Add paragraph
    </div>
  );

  const FinalColumn = () => (
    <div 
      ref={(node) => {
        finalColumnRef.current = node;
        drop(node);
      }}
      style={{ 
        width: columnWidth, 
        overflowY: "auto",
        background: isOver ? "#f0f8ff" : "transparent",
        border: isOver ? "2px dashed #007acc" : "2px solid transparent",
        borderRadius: 4,
        transition: "all 0.2s ease",
        position: "relative"
      }}
    >
      <div style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        background: "#e0e0e0",
        borderRadius: "4px 4px 0 0"
      }}>
        <h4 style={{ 
          margin: 0, 
          padding: "8px 12px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center"
        }}>
          <span>
            Final Letter
            {finalParagraphs.length > 0 && (
              <span style={{ fontSize: "12px", fontWeight: "normal", marginLeft: "8px" }}>
                ({finalParagraphs.length} paragraphs)
              </span>
            )}
          </span>
          <button
            id="copy-final-text-btn"
            onClick={copyFinalText}
            disabled={finalParagraphs.length === 0}
            style={{
              padding: "4px 8px",
              fontSize: "12px",
              background: finalParagraphs.length === 0 ? "#ccc" : "#3b82f6",
              color: "white",
              border: "none",
              borderRadius: 4,
              cursor: finalParagraphs.length === 0 ? "not-allowed" : "pointer",
              transition: "background 0.2s ease"
            }}
          >
            📋 Copy All
          </button>
        </h4>
      </div>
      
      <div style={{ padding: "8px" }}>
        <PlusButton onClick={() => addNewParagraph(0)} />
        
        {finalParagraphs.length === 0 ? (
          <div style={{
            padding: "20px",
            textAlign: "center",
            color: "#666",
            fontStyle: "italic",
            border: "2px dashed #ddd",
            borderRadius: 4,
            background: "#f9f9f9",
            margin: "4px 0"
          }}>
            Drag paragraphs here to build your final letter
          </div>
        ) : (
          finalParagraphs.map((p, idx) => {
            // Safety check: skip any undefined or invalid paragraphs
            if (!p || typeof p !== 'object') return null;
            
            // Ensure we have a safe vendor value
            const paragraphVendor = p.vendor;
            const paragraphColor = paragraphVendor ? (vendorColors[paragraphVendor] || "#eee") : "#ffffff";
            
            return (
              <div key={p.id || `paragraph-${idx}`}>
                <div data-paragraph-index={idx}>
                  <Paragraph
                    paragraph={p}
                    index={idx}
                    moveParagraph={moveFinalParagraph}
                    color={paragraphColor}
                    editable
                    onTextChange={(txt) => updateParagraphText(idx, txt)}
                    onFragmentSplit={(index, fragments) => 
                      handleFragmentSplit(index, fragments, p.text, fragments.map(f => f.text).join('\n\n'))
                    }
                    onDelete={() => deleteParagraph(idx)}
                  />
                </div>
                <PlusButton onClick={() => addNewParagraph(idx + 1)} />
              </div>
            );
          })
        )}
      </div>
    </div>
  );

  return (
    <HoverProvider>
      <div style={{ 
        height: "calc(100vh - 200px)", 
        marginTop: 20,
        display: "flex",
        flexDirection: "column"
      }}>
        {collapsedVendors.length > 0 && (
          <select
            onChange={(e) => {
              if (e.target.value) toggleCollapse(e.target.value);
              e.target.value = "";
            }}
            style={{ 
              marginBottom: 10,
              maxHeight: "100px",
              overflowY: "auto"
            }}
          >
            <option value="">Restore collapsed...</option>
            {collapsedVendors.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        )}
        
        <div style={{ 
          display: "flex", 
          gap: 10, 
          flex: 1,
          minHeight: 0
        }}>
          {visibleVendors.map((v) => (
            <div key={v} style={{ width: columnWidth, overflowY: "auto", position: "relative" }}>
              <h4 style={{ 
                textTransform: "capitalize", 
                margin: 0, 
                background: vendorColors?.[v] || "#f0f0f0",
                padding: "8px 12px",
                borderRadius: "4px 4px 0 0",
                position: "sticky",
                top: 0,
                zIndex: 10
              }}>
                {v}
                {loadingVendors.has(v) && (
                  <span style={{ marginLeft: "8px", fontSize: "12px" }}>Loading...</span>
                )}
                {failedVendors[v] && (
                  <span style={{ marginLeft: "8px", fontSize: "12px", color: "red" }}>Failed</span>
                )}
              </h4>
              
              <div style={{ padding: "8px" }}>
                {loadingVendors.has(v) ? (
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    height: "100px"
                  }}>
                    <div className="spinner" />
                  </div>
                ) : failedVendors[v] ? (
                  <div style={{
                    padding: "16px",
                    color: "red",
                    fontSize: "12px",
                    background: "#fff5f5",
                    border: "1px solid #fed7d7",
                    borderRadius: 4
                  }}>
                    <div style={{ marginBottom: "8px" }}>{failedVendors[v]}</div>
                    <button 
                      onClick={() => onRetry(v)}
                      style={{
                        padding: "4px 8px",
                        fontSize: "12px",
                        background: "#e53e3e",
                        color: "white",
                        border: "none",
                        borderRadius: 2,
                        cursor: "pointer"
                      }}
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  (vendorParagraphs[v] || []).map((p, i) => (
                    <Paragraph 
                      key={p.id} 
                      paragraph={p} 
                      index={i} 
                      moveParagraph={() => {}} 
                      color={vendorColors?.[v]} 
                      editable={false}
                    />
                  ))
                )}
              </div>
            </div>
          ))}
          
          <FinalColumn />
          
          <LetterCard 
            title="Original Letter" 
            text={originalLetter} 
            editable={false} 
            width={columnWidth} 
          />
        </div>
      </div>
    </HoverProvider>
  );
}

// Add spinner styles if not already present
if (!document.querySelector('#letter-tabs-styles')) {
  const style = document.createElement("style");
  style.id = 'letter-tabs-styles';
  style.innerHTML = `
    .spinner {
      width: 24px;
      height: 24px;
      border: 3px solid #e2e8f0;
      border-top-color: #3182ce;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin { 
      to { transform: rotate(360deg); } 
    }
  `;
  document.head.appendChild(style);
} 