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
  const [languageInput, setLanguageInput] = useState("");
  const [languageOptions, setLanguageOptions] = useState([
    { code: "en", label: "EN", enabled: true },
    { code: "de", label: "DE", enabled: true },
    { code: "it", label: "IT", enabled: false },
    { code: "fr", label: "FR", enabled: false },
  ]);

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
    console.log('🔄 moveFinalParagraph called:', { from, to, currentLength: finalParagraphs.length });
    
    setFinalParagraphs((prev) => {
      console.log('🔄 moveFinalParagraph executing with prev.length:', prev.length);
      
      // More comprehensive bounds checking
      if (
        typeof from !== 'number' || 
        typeof to !== 'number' || 
        from < 0 || 
        from >= prev.length || 
        to < 0 || 
        to > prev.length ||
        from === to ||
        !Array.isArray(prev) ||
        prev.length === 0
      ) {
        console.warn('❌ Invalid move indices:', { 
          from, 
          to, 
          arrayLength: prev.length, 
          fromType: typeof from,
          toType: typeof to,
          isArray: Array.isArray(prev),
          reason: from === to ? 'from === to' : 
                  from < 0 ? 'from < 0' :
                  from >= prev.length ? 'from >= array length' :
                  to < 0 ? 'to < 0' :
                  to > prev.length ? 'to > array length' :
                  prev.length === 0 ? 'empty array' : 'unknown'
        });
        return prev; // Return unchanged if indices are invalid
      }
      
      try {
        const copy = [...prev];
        console.log('📋 Before move - array:', copy.map((p, i) => ({ index: i, id: p.id, text: p.text?.substring(0, 20) })));
        
        const [moved] = copy.splice(from, 1);
        
        // Double-check that we have a valid item to move
        if (!moved) {
          console.warn('❌ No item found at index:', from);
          return prev;
        }
        
        console.log('📦 Moving item:', { from, to, movedId: moved.id, movedText: moved.text?.substring(0, 20) });
        
        copy.splice(to, 0, moved);
        
        console.log('✅ After move - array:', copy.map((p, i) => ({ index: i, id: p.id, text: p.text?.substring(0, 20) })));
        
        return copy;
      } catch (error) {
        console.error('❌ Error moving paragraph:', error, { from, to, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const handleFragmentSplit = (paragraphIndex, fragments, originalText, newText) => {
    setFinalParagraphs((prev) => {
      try {
        if (paragraphIndex < 0 || paragraphIndex >= prev.length) {
          console.warn('Invalid fragment split index:', { paragraphIndex, arrayLength: prev.length });
          return prev;
        }

        if (!Array.isArray(fragments) || fragments.length === 0) {
          console.warn('Invalid fragments for split:', fragments);
          return prev;
        }

        const copy = [...prev];
        const originalParagraph = copy[paragraphIndex];
        
        if (!originalParagraph) {
          console.warn('No paragraph found at index for split:', paragraphIndex);
          return prev;
        }
        
        // Create fragments for the parts that match original text
        const processedFragments = [];
        
        fragments.forEach(fragment => {
          if (!fragment || typeof fragment !== 'object') {
            console.warn('Invalid fragment:', fragment);
            return;
          }

          if (originalText && originalText.includes(fragment.text?.trim())) {
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
        
        if (processedFragments.length > 0) {
          copy.splice(paragraphIndex, 1, ...processedFragments);
        } else {
          console.warn('No valid fragments to replace with');
          return prev;
        }
        
        return copy;
      } catch (error) {
        console.error('Error handling fragment split:', error, { paragraphIndex, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const addParagraphAtPosition = (paragraph, targetIndex = null) => {
    console.log('➕ addParagraphAtPosition called:', { 
      paragraphId: paragraph?.id, 
      targetIndex, 
      currentLength: finalParagraphs.length 
    });
    
    if (!paragraph || typeof paragraph !== 'object') {
      console.warn('❌ Invalid paragraph to add:', paragraph);
      return;
    }

    const newParagraph = {
      ...paragraph,
      id: uuidv4(), // Give it a new ID for the final column
      sourceId: paragraph.sourceId || paragraph.id, // Track original source
      vendor: paragraph.vendor || null // Ensure vendor is never undefined
    };
    
    console.log('📝 Created new paragraph:', { 
      newId: newParagraph.id, 
      sourceId: newParagraph.sourceId, 
      vendor: newParagraph.vendor,
      text: newParagraph.text?.substring(0, 20)
    });

    setFinalParagraphs((prev) => {
      console.log('➕ addParagraphAtPosition executing with prev.length:', prev.length);
      
      try {
        if (targetIndex !== null) {
          // Ensure targetIndex is within valid bounds
          const safeIndex = Math.max(0, Math.min(targetIndex, prev.length));
          console.log('🎯 Adding at position:', { targetIndex, safeIndex, prevLength: prev.length });
          
          const copy = [...prev];
          copy.splice(safeIndex, 0, newParagraph);
          
          console.log('✅ After add - array:', copy.map((p, i) => ({ index: i, id: p.id, text: p.text?.substring(0, 20) })));
          
          return copy;
        }
        
        console.log('📎 Adding to end of array');
        const result = [...prev, newParagraph];
        console.log('✅ After append - array:', result.map((p, i) => ({ index: i, id: p.id, text: p.text?.substring(0, 20) })));
        
        return result;
      } catch (error) {
        console.error('❌ Error adding paragraph:', error, { targetIndex, arrayLength: prev.length });
        return prev;
      }
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
      try {
        // Ensure index is within valid bounds
        const safeIndex = Math.max(0, Math.min(index, prev.length));
        const copy = [...prev];
        copy.splice(safeIndex, 0, newParagraph);
        return copy;
      } catch (error) {
        console.error('Error adding new paragraph:', error, { index, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const deleteParagraph = (index) => {
    setFinalParagraphs((prev) => {
      try {
        if (index < 0 || index >= prev.length) {
          console.warn('Invalid delete index:', { index, arrayLength: prev.length });
          return prev;
        }
        const copy = [...prev];
        copy.splice(index, 1);
        return copy;
      } catch (error) {
        console.error('Error deleting paragraph:', error, { index, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const updateParagraphText = (index, newText) => {
    setFinalParagraphs((prev) => {
      try {
        if (index < 0 || index >= prev.length) {
          console.warn('Invalid update index:', { index, arrayLength: prev.length });
          return prev;
        }
        const copy = [...prev];
        copy[index] = { ...copy[index], text: newText };
        return copy;
      } catch (error) {
        console.error('Error updating paragraph text:', error, { index, arrayLength: prev.length });
        return prev;
      }
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

  // Drop zone for the scrollable content area
  const [{ isOver: isContentOver }, contentDrop] = useDrop({
    accept: ItemTypes.PARAGRAPH,
    drop(item, monitor) {
      if (monitor.didDrop()) return;
      
      // Calculate drop position based on mouse position within scrollable area
      const finalColumnRect = finalColumnRef.current?.getBoundingClientRect();
      const clientOffset = monitor.getClientOffset();
      
      if (finalColumnRect && clientOffset) {
        const relativeY = clientOffset.y - finalColumnRect.top;
        
        // Find the best insertion point among existing paragraphs
        const paragraphElements = finalColumnRef.current.querySelectorAll('[data-paragraph-index]');
        let targetIndex = finalParagraphs.length;
        
        for (let i = 0; i < paragraphElements.length; i++) {
          const rect = paragraphElements[i].getBoundingClientRect();
          const elementY = rect.top - finalColumnRect.top;
          const elementMiddle = elementY + (rect.height / 2);
          
          if (relativeY < elementMiddle) {
            targetIndex = i;
            break;
          }
        }
        
        addParagraphAtPosition(item.paragraph, targetIndex);
      } else {
        addParagraphAtPosition(item.paragraph);
      }
    },
    collect: (monitor) => ({
      isOver: monitor.isOver({ shallow: true })
    })
  });

  // Drop zone for the bottom area (always adds to end)
  const [{ isOver: isBottomOver }, bottomDrop] = useDrop({
    accept: ItemTypes.PARAGRAPH,
    drop(item, monitor) {
      if (monitor.didDrop()) return;
      addParagraphAtPosition(item.paragraph, finalParagraphs.length);
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

  const toggleLanguage = (code) => {
    setLanguageOptions((prev) =>
      prev.map((lang) =>
        lang.code === code ? { ...lang, enabled: !lang.enabled } : lang
      )
    );
  };

  const addLanguageFromSearch = () => {
    const code = languageInput.trim().toLowerCase();
    if (!code) return;

    setLanguageOptions((prev) => {
      const exists = prev.some((lang) => lang.code === code);
      if (exists) {
        return prev.map((lang) =>
          lang.code === code ? { ...lang, enabled: true } : lang
        );
      }
      const label = code.toUpperCase();
      return [...prev, { code, label, enabled: true }];
    });
    setLanguageInput("");
  };

  const enabledLanguages = languageOptions.filter((l) => l.enabled);

  const FinalColumn = () => (
    <div 
      style={{ 
        width: columnWidth, 
        borderRadius: 4,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        height: "100%" // Take full height of parent
      }}
    >
      <div style={{
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
      
      {/* Scrollable content area */}
      <div 
        ref={(node) => {
          finalColumnRef.current = node;
          contentDrop(node);
        }}
        style={{ 
          flex: 1,
          overflowY: "auto",
          padding: "8px",
          minHeight: 0, // Allow flex item to shrink
          background: isContentOver ? "#f0f8ff" : "transparent",
          border: isContentOver ? "2px dashed #007acc" : "2px solid transparent",
          borderRadius: "4px",
          transition: "all 0.2s ease"
        }}
      >
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
            if (!p || typeof p !== 'object') {
              console.warn('Invalid paragraph at index:', idx, p);
              return null;
            }
            
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
                    onFragmentSplit={(index, fragments) => {
                      try {
                        const fragmentText = Array.isArray(fragments) 
                          ? fragments.filter(f => f && f.text).map(f => f.text).join('\n\n') 
                          : '';
                        handleFragmentSplit(index, fragments, p.text, fragmentText);
                      } catch (error) {
                        console.error('Error in fragment split callback:', error);
                      }
                    }}
                    onDelete={() => deleteParagraph(idx)}
                    languages={enabledLanguages}
                  />
                </div>
                <PlusButton onClick={() => addNewParagraph(idx + 1)} />
              </div>
            );
          }).filter(Boolean) // Remove any null entries
        )}
      </div>
      
      {/* Fixed bottom drop zone - always visible */}
      <div 
        ref={bottomDrop}
        style={{
          minHeight: "50px",
          padding: "12px",
          textAlign: "center",
          color: isBottomOver ? "#007acc" : "#999",
          border: isBottomOver ? "2px dashed #007acc" : "2px dashed #ddd",
          borderRadius: "0 0 4px 4px",
          background: isBottomOver ? "#e8f4f8" : "#f9f9f9",
          fontSize: "12px",
          transition: "all 0.2s ease",
          flexShrink: 0, // Don't allow this to shrink
          cursor: "pointer"
        }}
        onMouseEnter={(e) => {
          if (!isBottomOver) {
            e.target.style.background = "#e8f4f8";
            e.target.style.borderColor = "#007acc";
            e.target.style.color = "#007acc";
          }
        }}
        onMouseLeave={(e) => {
          if (!isBottomOver) {
            e.target.style.background = "#f9f9f9";
            e.target.style.borderColor = "#ddd";
            e.target.style.color = "#999";
          }
        }}
        onClick={() => addParagraphAtPosition({ text: "", vendor: null }, finalParagraphs.length)}
      >
        Drop here to add to bottom
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
        <div style={{ marginBottom: 10, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span style={{ fontWeight: 600, fontSize: 13 }}>Languages:</span>
          {languageOptions.slice(0, 4).map((lang) => (
            <label key={lang.code} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
              <input
                type="checkbox"
                checked={lang.enabled}
                onChange={() => toggleLanguage(lang.code)}
                style={{ cursor: "pointer" }}
              />
              {lang.label}
            </label>
          ))}
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="text"
              value={languageInput}
              onChange={(e) => setLanguageInput(e.target.value)}
              placeholder="Add language code (e.g., es)"
              style={{ fontSize: 12, padding: "4px 6px", width: 150 }}
            />
            <button
              onClick={addLanguageFromSearch}
              style={{
                padding: "4px 8px",
                fontSize: 12,
                background: "#3b82f6",
                color: "white",
                border: "none",
                borderRadius: 4,
                cursor: "pointer"
              }}
            >
              Add
            </button>
          </div>
        </div>
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
                    languages={enabledLanguages}
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
            languages={enabledLanguages}
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