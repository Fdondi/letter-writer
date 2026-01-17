import React, { useState, useRef, useEffect } from "react";
import { useDrag, useDrop } from "react-dnd";
import { HoverContext } from "../contexts/HoverContext";
import { v4 as uuidv4 } from "uuid";
import { translateText } from "../utils/translate";
import { ItemTypes } from "../constants";
import LanguageSelector from "./LanguageSelector";
import { useLanguages } from "../contexts/LanguageContext";

function splitTextIntoFragments(text, originalParagraph) {
  if (!text) return [];
  
  // Split on double newlines to maintain paragraph structure
  const parts = text.split(/\n\s*\n/);
  return parts.filter(part => part.trim()).map(part => ({
    id: uuidv4(),
    text: part.trim(),
    vendor: originalParagraph.vendor,
    sourceId: originalParagraph.sourceId || originalParagraph.id,
    isFragment: true,
    originalText: originalParagraph.text
  }));
}

export default function Paragraph({ 
  paragraph, 
  index, 
  moveParagraph, 
  color, 
  editable = false, 
  onTextChange,
  onFragmentSplit,
  onDelete,
  dropZoneRef = null,
  languages = [],
  // Controlled mode props
  translations: externalTranslations,
  viewLanguage: externalViewLanguage,
  onTranslationLoaded,
  onViewLanguageChange
}) {
  const ref = useRef(null);
  const textRef = useRef(null);
  const textareaRef = useRef(null);
  const { hoverId, setHoverId } = React.useContext(HoverContext);
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(paragraph.text);
  const [isCopyMode, setIsCopyMode] = useState(false);
  const [cursorPosition, setCursorPosition] = useState(null);
  
  // Local state (used if not controlled)
  const [localViewLanguage, setLocalViewLanguage] = useState("source");
  const [localTranslations, setLocalTranslations] = useState({});
  const [isTranslating, setIsTranslating] = useState(false);
  const [translationError, setTranslationError] = useState(null);
  const [lastTranslatedSource, setLastTranslatedSource] = useState(paragraph.text);

  // Determine effective state (controlled vs local)
  const translations = externalTranslations || localTranslations;
  const viewLanguage = externalViewLanguage || localViewLanguage;
  const isControlled = externalTranslations !== undefined;

  // Drop zone for reordering within final column
  const [, drop] = useDrop(() => ({
    accept: ItemTypes.PARAGRAPH,
    hover(item, monitor) {
      // Only allow reordering if we have a real moveParagraph function 
      // (not the empty function from vendor columns)
      if (!moveParagraph || moveParagraph.toString() === "() => {}" || isCopyMode) return;
      if (item.index === index) return;
      
      // Only reorder if the item has a sourceId matching our final column context
      // This prevents vendor column paragraphs from interfering with final column reordering
      if (!item.isFromFinalColumn) return;
      
      const hoverBoundingRect = ref.current?.getBoundingClientRect();
      const hoverMiddleY = (hoverBoundingRect.bottom - hoverBoundingRect.top) / 2;
      const clientOffset = monitor.getClientOffset();
      const hoverClientY = clientOffset.y - hoverBoundingRect.top;

      // Only perform the move when the mouse has crossed half of the items height
      if (item.index < index && hoverClientY < hoverMiddleY) return;
      if (item.index > index && hoverClientY > hoverMiddleY) return;

      moveParagraph(item.index, index);
      item.index = index;
    },
  }), [index, moveParagraph, isCopyMode]);

  // Drag functionality
  const [{ isDragging }, drag] = useDrag({
    type: ItemTypes.PARAGRAPH,
    item: () => ({
      paragraph: {
        ...paragraph,
        sourceId: paragraph.sourceId || paragraph.id
      },
      index,
      // Mark whether this item is from the final column (has real moveParagraph function)
      isFromFinalColumn: moveParagraph && moveParagraph.toString() !== "() => {}"
    }),
    canDrag: !isCopyMode && !isEditing,
    collect: (monitor) => ({ isDragging: monitor.isDragging() }),
  });

  // Combine drag and drop refs
  if (dropZoneRef) {
    drag(dropZoneRef(ref));
  } else {
    drag(drop(ref));
  }

  const handleTextChange = (newText) => {
    setEditText(newText);
    
    if (onFragmentSplit && newText !== paragraph.text) {
      // Check if text should be split into fragments
      const fragments = splitTextIntoFragments(newText, paragraph);
      if (fragments.length > 1) {
        onFragmentSplit(index, fragments);
        return;
      }
    }
    
    if (onTextChange) {
      onTextChange(newText);
    }
  };

  const handleBlur = () => {
    setIsEditing(false);
    setCursorPosition(null);
    handleTextChange(editText);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      handleBlur();
    }
    if (e.key === 'Escape') {
      setEditText(paragraph.text);
      setIsEditing(false);
      setCursorPosition(null);
    }
  };

  // Calculate cursor position from click coordinates
  const getCursorPositionFromClick = (e, element) => {
    if (!element) return 0;
    
    try {
      // Use caretRangeFromPoint if available (most modern browsers)
      if (document.caretRangeFromPoint) {
        const range = document.caretRangeFromPoint(e.clientX, e.clientY);
        if (range) {
          // Create a temporary range to measure from start of element
          const tempRange = document.createRange();
          tempRange.selectNodeContents(element);
          tempRange.setEnd(range.endContainer, range.endOffset);
          return tempRange.toString().length;
        }
      }
      
      // Fallback: use caretPositionFromPoint (Firefox)
      if (document.caretPositionFromPoint) {
        const caretPos = document.caretPositionFromPoint(e.clientX, e.clientY);
        if (caretPos) {
          const range = document.createRange();
          range.setStart(element, 0);
          range.setEnd(caretPos.offsetNode, caretPos.offset);
          return range.toString().length;
        }
      }
      
      // Fallback: approximate based on text content and click position
      const rect = element.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      
      // Get computed styles to match textarea
      const styles = window.getComputedStyle(element);
      const font = `${styles.fontSize} ${styles.fontFamily}`;
      const lineHeight = parseFloat(styles.lineHeight) || parseFloat(styles.fontSize) * 1.2;
      
      // Approximate: assume each line has similar width
      // This is a rough estimate, but better than always starting at 0
      const text = element.textContent || element.innerText || '';
      const lines = text.split('\n');
      const lineIndex = Math.floor(y / lineHeight);
      const targetLine = lines[Math.min(lineIndex, lines.length - 1)] || '';
      
      // Estimate character position on the line based on x position
      // This is approximate - font metrics would be needed for accuracy
      const avgCharWidth = 8; // Rough estimate
      const charPosOnLine = Math.max(0, Math.floor(x / avgCharWidth));
      const position = Math.min(
        text.length,
        lines.slice(0, lineIndex).join('\n').length + (lineIndex > 0 ? 1 : 0) + charPosOnLine
      );
      
      return position;
    } catch (err) {
      console.warn('Error calculating cursor position:', err);
      return 0;
    }
  };

  const handleDoubleClick = (e) => {
    if (!editable) {
      e.stopPropagation();
      setIsCopyMode(true);
    }
  };

  const handleMouseLeave = () => {
    // Don't exit copy mode on mouse leave - allow text selection to work
    // Copy mode will exit on click outside or Escape key
  };

  const handleMouseDown = (e) => {
    // If clicking on text content and paragraph is editable, prevent drag
    if (editable && textRef.current && textRef.current.contains(e.target)) {
      e.stopPropagation();
    }
    // If in copy mode, prevent drag
    if (isCopyMode) {
      e.stopPropagation();
    }
    // If clicking outside the paragraph while in copy mode, exit copy mode
    if (isCopyMode && ref.current && !ref.current.contains(e.target)) {
      setIsCopyMode(false);
    }
  };

  // Exit copy mode on Escape key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && isCopyMode) {
        setIsCopyMode(false);
      }
    };
    
    if (isCopyMode) {
      document.addEventListener('keydown', handleKeyDown);
      return () => {
        document.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [isCopyMode]);

  // Exit copy mode when clicking outside the paragraph
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (isCopyMode && ref.current && !ref.current.contains(e.target)) {
        // Only exit if we're not in the middle of a text selection
        const selection = window.getSelection();
        if (!selection || selection.toString().length === 0) {
          setIsCopyMode(false);
        }
      }
    };
    
    if (isCopyMode) {
      // Use a small delay to allow text selection to complete
      const timeoutId = setTimeout(() => {
        document.addEventListener('click', handleClickOutside);
      }, 100);
      
      return () => {
        clearTimeout(timeoutId);
        document.removeEventListener('click', handleClickOutside);
      };
    }
  }, [isCopyMode]);

  // Update edit text when paragraph changes
  useEffect(() => {
    setEditText(paragraph.text);
  }, [paragraph.text]);

  // Set cursor position in textarea after it's mounted
  useEffect(() => {
    if (isEditing && textareaRef.current && cursorPosition !== null) {
      // Use setTimeout to ensure the textarea is fully rendered
      setTimeout(() => {
        if (textareaRef.current) {
          const position = Math.min(cursorPosition, textareaRef.current.value.length);
          textareaRef.current.setSelectionRange(position, position);
          textareaRef.current.focus();
        }
      }, 0);
    }
  }, [isEditing, cursorPosition]);

  useEffect(() => {
    // Reset translation cache when the underlying paragraph changes
    if (paragraph.text !== lastTranslatedSource) {
      if (!isControlled) {
        setLocalTranslations({});
        setLocalViewLanguage("source");
      } else if (onViewLanguageChange) {
        // If controlled, we can't force reset parent state easily here, 
        // but parent should handle it (e.g. in updateParagraphText)
      }
      setLastTranslatedSource(paragraph.text);
    }
  }, [paragraph.text, lastTranslatedSource, isControlled, onViewLanguageChange]);

  const displayText = (() => {
    if (viewLanguage !== "source" && translations[viewLanguage] && !isEditing) {
      return translations[viewLanguage];
    }
    return paragraph.text;
  })();

  const requestTranslation = async (targetLanguage) => {
    if (isTranslating) return;
    
    // Check cache
    if (translations[targetLanguage] && lastTranslatedSource === paragraph.text) {
      if (isControlled && onViewLanguageChange) {
        onViewLanguageChange(targetLanguage);
      } else {
        setLocalViewLanguage(targetLanguage);
      }
      return;
    }

    setIsTranslating(true);
    setTranslationError(null);
    try {
      const translated = await translateText(paragraph.text, targetLanguage, null);
      
      if (isControlled && onTranslationLoaded) {
        onTranslationLoaded(targetLanguage, translated);
        if (onViewLanguageChange) {
            onViewLanguageChange(targetLanguage);
        }
      } else {
        setLocalTranslations((prev) => ({ ...prev, [targetLanguage]: translated }));
        setLocalViewLanguage(targetLanguage);
      }
      
      setLastTranslatedSource(paragraph.text);
    } catch (err) {
      setTranslationError(err.message || "Translation failed");
    } finally {
      setIsTranslating(false);
    }
  };

  // Use language context if available, otherwise use provided languages
  let languageContext;
  try {
    languageContext = useLanguages();
  } catch (e) {
    languageContext = null;
  }
  const buttonLanguages = languages.length ? languages : (languageContext?.enabledLanguages || []);

  const TranslationBar = (
    <div 
      onClick={(e) => e.stopPropagation()}
      style={{ display: "flex", justifyContent: "flex-start", alignItems: "center", gap: 6, marginBottom: 6, flexWrap: "wrap" }}
    >
      {isTranslating && <span style={{ fontSize: "10px", color: "var(--secondary-text-color)" }}>Translating…</span>}
      <LanguageSelector
        languages={buttonLanguages}
        viewLanguage={viewLanguage}
        onLanguageChange={(code) => {
          if (code === "source") {
            if (isControlled && onViewLanguageChange) {
              onViewLanguageChange("source");
            } else {
              setLocalViewLanguage("source");
            }
          } else {
            requestTranslation(code);
          }
        }}
        hasTranslation={(code) => Boolean(translations[code])}
        disabled={false}
        isTranslating={isTranslating}
        size="small"
      />
    </div>
  );

  const isDarkMode = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const idleBg = color?.replace(/hsl\(([^)]+)\)/, isDarkMode ? "hsla($1,0.5)" : "hsla($1,0.3)") || "var(--panel-bg)";
  const activeBg = color || "var(--header-bg)";
  
  // Handle white background for user text
  if (paragraph.isUserText || !paragraph.vendor) {
    const userIdleBg = "var(--input-bg)";
    const userActiveBg = "var(--header-bg)";
    const sourceId = paragraph.sourceId || paragraph.id;
    const isHighlighted = hoverId === paragraph.id || hoverId === sourceId;

    return (
      <div
        ref={ref}
        style={{
          opacity: isDragging ? 0.4 : 1,
        background: isHighlighted ? userActiveBg : userIdleBg,
          padding: 8,
          borderRadius: 4,
          cursor: isCopyMode ? "text" : "move",
          marginBottom: 4,
          border: isCopyMode ? "2px solid #007acc" : "1px solid var(--border-color)",
          position: "relative",
        transition: "all 0.2s ease",
        transform: viewLanguage !== "source" ? "rotateY(6deg)" : "rotateY(0deg)",
          transformStyle: "preserve-3d",
          perspective: "1000px",
          color: 'var(--text-color)'
        }}
        onMouseEnter={() => setHoverId(sourceId)}
        onMouseLeave={handleMouseLeave}
        onMouseDown={handleMouseDown}
        onDoubleClick={handleDoubleClick}
      >
        {isCopyMode && (
          <div style={{
            position: "absolute",
            top: -8,
            left: 4,
            fontSize: "10px",
            background: "#007acc",
            color: "white",
            padding: "1px 4px",
            borderRadius: 2
          }}>
            copy mode
          </div>
        )}
        
        <div style={{
          position: "absolute",
          top: -8,
          right: 4,
          fontSize: "10px",
          background: "var(--card-bg)",
          padding: "1px 4px",
          borderRadius: 2,
          color: "var(--secondary-text-color)",
          border: "1px solid var(--border-color)"
        }}>
          user text
        </div>
        
        {TranslationBar}
        {translationError && (
          <div style={{ color: "var(--error-text)", fontSize: "11px", marginBottom: 4 }}>
            {translationError}
          </div>
        )}

        {onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            style={{
              position: "absolute",
              top: -6,
              right: -6,
              background: "#ef4444",
              color: "white",
              border: "none",
              borderRadius: 2,
              width: 16,
              height: 16,
              fontSize: "10px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center"
            }}
            title="Delete paragraph"
          >
            ×
          </button>
        )}
        
        {editable ? (
          isEditing ? (
            <textarea
              ref={textareaRef}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onBlur={handleBlur}
              onKeyDown={handleKeyDown}
              style={{
                width: "100%",
                minHeight: "120px", // Larger minimum height
                resize: "vertical",
                border: "1px solid var(--border-color)",
                borderRadius: 2,
                padding: 8,
                fontFamily: "inherit",
                fontSize: "inherit",
                outline: "2px solid #007acc",
                backgroundColor: 'var(--input-bg)',
                color: 'var(--text-color)'
              }}
              autoFocus
            />
          ) : (
            <div
              ref={textRef}
              onClick={(e) => {
                e.stopPropagation();
                // Calculate cursor position from click
                const position = getCursorPositionFromClick(e, textRef.current);
                setCursorPosition(position);
                setIsEditing(true);
                // If we are viewing a translation, populate edit text with the translation
                // so the user edits what they see. This effectively "switches the original".
                if (displayText !== paragraph.text) {
                    setEditText(displayText);
                }
              }}
              style={{
                whiteSpace: "pre-wrap",
                cursor: "text",
                minHeight: "20px",
                padding: 2,
                userSelect: "text"
              }}
            >
              {displayText || "Click to edit..."}
            </div>
          )
        ) : (
          <div 
            ref={textRef}
            style={{ 
              whiteSpace: "pre-wrap", 
              userSelect: isCopyMode ? "text" : "none",
              cursor: isCopyMode ? "text" : "move"
            }}
          >
            {displayText}
          </div>
        )}
      </div>
    );
  }

  // Regular AI-generated paragraph
  const sourceId = paragraph.sourceId || paragraph.id;
  const isHighlighted = hoverId === paragraph.id || hoverId === sourceId;

  return (
    <div
      ref={ref}
      style={{
        opacity: isDragging ? 0.4 : 1,
        background: isHighlighted ? activeBg : idleBg,
        padding: 8,
        borderRadius: 4,
        cursor: isCopyMode ? "text" : "move",
        marginBottom: 4,
        border: isCopyMode ? "2px solid #007acc" : (paragraph.isFragment ? "1px dashed var(--secondary-text-color)" : "1px solid transparent"),
        position: "relative",
        transition: "all 0.2s ease",
        transform: viewLanguage !== "source" ? "rotateY(6deg)" : "rotateY(0deg)",
        transformStyle: "preserve-3d",
        perspective: "1000px",
        color: isDarkMode ? 'white' : 'black' // High contrast for vendor colored backgrounds
      }}
      onMouseEnter={() => setHoverId(sourceId)}
      onMouseLeave={handleMouseLeave}
      onMouseDown={handleMouseDown}
      onDoubleClick={handleDoubleClick}
    >
      {isCopyMode && (
        <div style={{
          position: "absolute",
          top: -8,
          left: 4,
          fontSize: "10px",
          background: "#007acc",
          color: "white",
          padding: "1px 4px",
          borderRadius: 2
        }}>
          copy mode
        </div>
      )}
      
      {paragraph.isFragment && (
        <div style={{
          position: "absolute",
          top: -8,
          right: 4,
          fontSize: "10px",
          background: color || "var(--border-color)",
          padding: "1px 4px",
          borderRadius: 2,
          color: "var(--secondary-text-color)"
        }}>
          fragment
        </div>
      )}
      
      {TranslationBar}
      {translationError && (
        <div style={{ color: "var(--error-text)", fontSize: "11px", marginBottom: 4 }}>
          {translationError}
        </div>
      )}

      {onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          style={{
            position: "absolute",
              top: -6,
              right: -6,
            background: "#ef4444",
            color: "white",
            border: "none",
            borderRadius: 2,
            width: 16,
            height: 16,
            fontSize: "10px",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center"
          }}
          title="Delete paragraph"
        >
          ×
        </button>
      )}
      
      {editable ? (
        isEditing ? (
          <textarea
            ref={textareaRef}
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            style={{
              width: "100%",
              minHeight: "120px", // Larger minimum height
              resize: "vertical",
              border: "1px solid var(--border-color)",
              borderRadius: 2,
              padding: 8,
              fontFamily: "inherit",
              fontSize: "inherit",
              outline: "2px solid #007acc",
              backgroundColor: 'var(--input-bg)',
              color: 'var(--text-color)'
            }}
            autoFocus
          />
        ) : (
          <div
            ref={textRef}
            onClick={(e) => {
              e.stopPropagation();
              // Calculate cursor position from click
              const position = getCursorPositionFromClick(e, textRef.current);
              setCursorPosition(position);
              setIsEditing(true);
            }}
            style={{
              whiteSpace: "pre-wrap",
              cursor: "text",
              minHeight: "20px",
              padding: 2,
              userSelect: "text"
            }}
          >
            {paragraph.text || "Click to edit..."}
          </div>
        )
      ) : (
        <div 
          ref={textRef}
          style={{ 
            whiteSpace: "pre-wrap", 
            userSelect: isCopyMode ? "text" : "none",
            cursor: isCopyMode ? "text" : "move"
          }}
        >
          {displayText}
        </div>
      )}
    </div>
  );
} 