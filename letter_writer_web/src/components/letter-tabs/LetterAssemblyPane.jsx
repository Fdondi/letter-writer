import React, { useState, useRef, useEffect, useLayoutEffect } from "react";
import { useDrop } from "react-dnd";
import { v4 as uuidv4 } from "uuid";
import Paragraph from "../Paragraph";
import LanguageSelector from "../LanguageSelector";
import { ItemTypes } from "../../constants";
import { normalizeForMatch } from "../../utils/textMatch";
import { translateText } from "../../utils/translate";
import SaveAndCopyButton, {
  SaveCopyErrorBanner,
  useSaveAndCopy,
} from "../SaveAndCopyButton";

function PlusButton({ onClick, style = {} }) {
  return (
    <div
      onClick={onClick}
      style={{
        padding: "4px 8px",
        margin: "2px 0",
        textAlign: "center",
        cursor: "pointer",
        color: "var(--secondary-text-color)",
        border: "1px dashed var(--border-color)",
        borderRadius: 4,
        background: "var(--panel-bg)",
        fontSize: "12px",
        transition: "all 0.2s ease",
        ...style,
      }}
      onMouseEnter={(e) => {
        e.target.style.background = "var(--header-bg)";
        e.target.style.borderColor = "var(--secondary-text-color)";
      }}
      onMouseLeave={(e) => {
        e.target.style.background = "var(--panel-bg)";
        e.target.style.borderColor = "var(--border-color)";
      }}
    >
      + Add paragraph
    </div>
  );
}

export default function LetterAssemblyPane({
  finalParagraphs,
  setFinalParagraphs,
  vendorColors,
  requirements,
  selectedKeyTerm,
  languageOptions,
  onSave,
  savingFinal = false,
  vendorColumnWidthPx,
  onHeaderClick,
  isExpanded = false,
  onClose,
  useOverlayWidth = false,
  onAssemblyTextChange,
}) {
  const [translationStates, setTranslationStates] = useState({});
  const [translateAllViewLanguage, setTranslateAllViewLanguage] = useState("source");
  const [translateAllInProgress, setTranslateAllInProgress] = useState(false);
  const [columnError, setColumnError] = useState(null);
  const finalColumnRef = useRef(null);
  const scrollPositionRef = useRef(0);

  const captureFinalColumnScroll = () => {
    const el = finalColumnRef.current;
    if (!el) return;
    scrollPositionRef.current = el.scrollTop;
  };

  const applyFinalColumnScrollRestore = () => {
    const el = finalColumnRef.current;
    if (!el) return;
    const max = Math.max(0, el.scrollHeight - el.clientHeight);
    el.scrollTop = Math.min(scrollPositionRef.current, max);
  };

  const handleScroll = (e) => {
    if (e.target === finalColumnRef.current) {
      scrollPositionRef.current = e.target.scrollTop;
    }
  };

  useLayoutEffect(() => {
    applyFinalColumnScrollRestore();
  }, [finalParagraphs, translationStates]);

  const moveFinalParagraph = (from, to) => {
    captureFinalColumnScroll();

    setFinalParagraphs((prev) => {
      if (
        typeof from !== "number" ||
        typeof to !== "number" ||
        from < 0 ||
        from >= prev.length ||
        to < 0 ||
        to > prev.length ||
        from === to ||
        !Array.isArray(prev) ||
        prev.length === 0
      ) {
        console.warn("❌ Invalid move indices:", {
          from,
          to,
          arrayLength: prev.length,
          fromType: typeof from,
          toType: typeof to,
          isArray: Array.isArray(prev),
          reason:
            from === to
              ? "from === to"
              : from < 0
                ? "from < 0"
                : from >= prev.length
                  ? "from >= array length"
                  : to < 0
                    ? "to < 0"
                    : to > prev.length
                      ? "to > array length"
                      : prev.length === 0
                        ? "empty array"
                        : "unknown",
        });
        return prev;
      }

      try {
        const copy = [...prev];
        const [moved] = copy.splice(from, 1);
        if (!moved) {
          console.warn("❌ No item found at index:", from);
          return prev;
        }
        copy.splice(to, 0, moved);
        return copy;
      } catch (error) {
        console.error("❌ Error moving paragraph:", error, { from, to, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const handleFragmentSplit = (paragraphIndex, fragments, originalText) => {
    captureFinalColumnScroll();

    setFinalParagraphs((prev) => {
      try {
        if (paragraphIndex < 0 || paragraphIndex >= prev.length) {
          console.warn("Invalid fragment split index:", { paragraphIndex, arrayLength: prev.length });
          return prev;
        }

        if (!Array.isArray(fragments) || fragments.length === 0) {
          console.warn("Invalid fragments for split:", fragments);
          return prev;
        }

        const copy = [...prev];
        const originalParagraph = copy[paragraphIndex];

        if (!originalParagraph) {
          console.warn("No paragraph found at index for split:", paragraphIndex);
          return prev;
        }

        const paragraphOriginalText =
          originalParagraph.originalText !== undefined
            ? originalParagraph.originalText
            : originalParagraph.text || "";

        const processedFragments = [];

        fragments.forEach((fragment) => {
          if (!fragment || typeof fragment !== "object") {
            console.warn("Invalid fragment:", fragment);
            return;
          }

          if (originalText && originalText.includes(fragment.text?.trim())) {
            processedFragments.push({
              ...fragment,
              vendor: originalParagraph.vendor,
              sourceId: originalParagraph.sourceId || originalParagraph.id,
              originalText: fragment.originalText || paragraphOriginalText,
            });
          } else {
            processedFragments.push({
              ...fragment,
              vendor: null,
              sourceId: null,
              isUserText: true,
              originalText: "",
            });
          }
        });

        if (processedFragments.length > 0) {
          copy.splice(paragraphIndex, 1, ...processedFragments);
        } else {
          console.warn("No valid fragments to replace with");
          return prev;
        }

        return copy;
      } catch (error) {
        console.error("Error handling fragment split:", error, {
          paragraphIndex,
          arrayLength: prev.length,
        });
        return prev;
      }
    });
  };

  const addParagraphAtPosition = (paragraph, targetIndex = null) => {
    if (!paragraph || typeof paragraph !== "object") {
      console.warn("❌ Invalid paragraph to add:", paragraph);
      return;
    }

    const newParagraph = {
      ...paragraph,
      id: uuidv4(),
      sourceId: paragraph.sourceId || paragraph.id,
      vendor: paragraph.vendor || null,
      originalText: paragraph.text || "",
    };

    captureFinalColumnScroll();

    setFinalParagraphs((prev) => {
      try {
        if (targetIndex !== null) {
          const safeIndex = Math.max(0, Math.min(targetIndex, prev.length));
          const copy = [...prev];
          copy.splice(safeIndex, 0, newParagraph);
          return copy;
        }
        return [...prev, newParagraph];
      } catch (error) {
        console.error("❌ Error adding paragraph:", error, { targetIndex, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const addNewParagraph = (index) => {
    captureFinalColumnScroll();

    const newParagraph = {
      id: uuidv4(),
      text: "",
      vendor: null,
      sourceId: null,
      isUserText: true,
      originalText: "",
    };

    setFinalParagraphs((prev) => {
      try {
        const safeIndex = Math.max(0, Math.min(index, prev.length));
        const copy = [...prev];
        copy.splice(safeIndex, 0, newParagraph);
        return copy;
      } catch (error) {
        console.error("Error adding new paragraph:", error, { index, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const deleteParagraph = (index) => {
    captureFinalColumnScroll();

    setFinalParagraphs((prev) => {
      try {
        if (index < 0 || index >= prev.length) {
          console.warn("Invalid delete index:", { index, arrayLength: prev.length });
          return prev;
        }
        const copy = [...prev];
        copy.splice(index, 1);
        return copy;
      } catch (error) {
        console.error("Error deleting paragraph:", error, { index, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const getDisplayText = (paragraph) => {
    const state = translationStates[paragraph.id];
    if (state && state.viewLanguage !== "source" && state.translations[state.viewLanguage]) {
      return state.translations[state.viewLanguage];
    }
    return paragraph.text;
  };

  const updateParagraphText = (index, newText) => {
    setFinalParagraphs((prev) => {
      try {
        if (index < 0 || index >= prev.length) {
          console.warn("Invalid update index:", { index, arrayLength: prev.length });
          return prev;
        }
        const copy = [...prev];
        const id = copy[index].id;
        const paragraph = copy[index];

        setTranslationStates((prevStates) => {
          if (!prevStates[id]) return prevStates;
          const next = { ...prevStates };
          delete next[id];
          return next;
        });

        const originalText =
          paragraph.originalText !== undefined ? paragraph.originalText : paragraph.text || "";

        copy[index] = {
          ...paragraph,
          text: newText,
          originalText,
        };
        return copy;
      } catch (error) {
        console.error("Error updating paragraph text:", error, { index, arrayLength: prev.length });
        return prev;
      }
    });
  };

  const finalAssemblyText = React.useMemo(() => {
    try {
      return finalParagraphs.map(getDisplayText).join("\n\n");
    } catch {
      return "";
    }
  }, [finalParagraphs, translationStates]);

  const finalAssemblyTextNormalized = React.useMemo(
    () => normalizeForMatch(finalAssemblyText),
    [finalAssemblyText]
  );

  useEffect(() => {
    onAssemblyTextChange?.({
      text: finalAssemblyText,
      normalized: finalAssemblyTextNormalized,
    });
  }, [finalAssemblyText, finalAssemblyTextNormalized, onAssemblyTextChange]);

  const saveCopy = useSaveAndCopy({
    letterText: finalAssemblyText,
    onSave,
    saving: savingFinal,
    resetKey: finalAssemblyText,
  });

  const translateAllParagraphsTo = async (targetLanguage) => {
    if (finalParagraphs.length === 0 || targetLanguage === "source") {
      setTranslationStates((prev) => {
        const next = { ...prev };
        Object.keys(next).forEach((id) => {
          next[id] = { ...next[id], viewLanguage: "source" };
        });
        return next;
      });
      setTranslateAllViewLanguage("source");
      return;
    }
    setTranslateAllInProgress(true);
    setColumnError(null);
    try {
      const updates = {};
      for (let i = 0; i < finalParagraphs.length; i++) {
        const p = finalParagraphs[i];
        if (!p?.text) continue;
        const translated = await translateText(p.text, targetLanguage, null);
        updates[p.id] = {
          viewLanguage: targetLanguage,
          translations: { [targetLanguage]: translated },
        };
      }
      setTranslationStates((prev) => {
        const next = { ...prev };
        Object.entries(updates).forEach(([id, state]) => {
          next[id] = {
            ...(next[id] || {}),
            ...state,
            translations: { ...(next[id]?.translations || {}), ...state.translations },
          };
        });
        return next;
      });
      setTranslateAllViewLanguage(targetLanguage);
    } catch (e) {
      setColumnError(e.message || "Translation failed");
    } finally {
      setTranslateAllInProgress(false);
    }
  };

  const [{ isOver: isContentOver }, contentDrop] = useDrop({
    accept: ItemTypes.PARAGRAPH,
    drop(item, monitor) {
      if (monitor.didDrop()) return;

      const finalColumnRect = finalColumnRef.current?.getBoundingClientRect();
      const clientOffset = monitor.getClientOffset();

      if (finalColumnRect && clientOffset) {
        const relativeY = clientOffset.y - finalColumnRect.top;
        const paragraphElements = finalColumnRef.current.querySelectorAll("[data-paragraph-index]");
        let targetIndex = finalParagraphs.length;

        for (let i = 0; i < paragraphElements.length; i++) {
          const rect = paragraphElements[i].getBoundingClientRect();
          const elementY = rect.top - finalColumnRect.top;
          const elementMiddle = elementY + rect.height / 2;

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
      isOver: monitor.isOver({ shallow: true }),
    }),
  });

  const [{ isOver: isBottomOver }, bottomDrop] = useDrop({
    accept: ItemTypes.PARAGRAPH,
    drop(item, monitor) {
      if (monitor.didDrop()) return;
      addParagraphAtPosition(item.paragraph, finalParagraphs.length);
    },
    collect: (monitor) => ({
      isOver: monitor.isOver({ shallow: true }),
    }),
  });

  return (
    <div
      style={{
        width: useOverlayWidth ? "100%" : vendorColumnWidthPx,
        minWidth: useOverlayWidth ? 0 : vendorColumnWidthPx,
        flexShrink: useOverlayWidth ? undefined : 0,
        borderRadius: 4,
        position: "relative",
        display: "flex",
        flexDirection: "column",
        backgroundColor: "var(--card-bg)",
        border: "1px solid var(--border-color)",
        height: "100%",
      }}
    >
      <div style={{ background: "var(--header-bg)", borderRadius: "4px 4px 0 0" }}>
        <h4
          style={{
            margin: 0,
            padding: "8px 12px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            color: "var(--text-color)",
          }}
        >
          <span>Final Letter</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {onHeaderClick && !isExpanded && (
              <button
                type="button"
                onClick={onHeaderClick}
                title="Expand to 80% width"
                style={{
                  padding: "2px 8px",
                  fontSize: "12px",
                  background: "var(--panel-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                Expand
              </button>
            )}
            {isExpanded && onClose && (
              <button
                type="button"
                onClick={onClose}
                title="Close expanded view"
                style={{
                  padding: "2px 8px",
                  fontSize: "12px",
                  background: "var(--panel-bg)",
                  color: "var(--text-color)",
                  border: "1px solid var(--border-color)",
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                × Close
              </button>
            )}
          </div>
        </h4>
        <div
          style={{
            padding: "6px 12px 8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: 8,
            flexWrap: "wrap",
            borderTop: "1px solid var(--border-color)",
          }}
        >
          <LanguageSelector
            languages={languageOptions}
            viewLanguage={translateAllViewLanguage}
            onLanguageChange={translateAllParagraphsTo}
            hasTranslation={(code) => translateAllViewLanguage === code}
            isTranslating={translateAllInProgress}
            size="tiny"
          />
          <SaveAndCopyButton
            id="save-copy-btn"
            onClick={saveCopy.handleClick}
            disabled={saveCopy.disabled}
            savedState={saveCopy.buttonSavedState}
            label={saveCopy.label}
          />
        </div>
      </div>
      <SaveCopyErrorBanner message={saveCopy.saveError || columnError} />
      <div
        ref={(node) => {
          finalColumnRef.current = node;
          contentDrop(node);
        }}
        onScroll={handleScroll}
        style={{
          flex: 1,
          padding: "8px",
          background: isContentOver ? "var(--header-bg)" : "transparent",
          border: isContentOver ? "2px dashed #007acc" : "2px solid transparent",
          borderRadius: "4px",
          transition: "all 0.2s ease",
          overflowY: "auto",
          minHeight: 0,
        }}
      >
        <PlusButton onClick={() => addNewParagraph(0)} />

        {finalParagraphs.length === 0 ? (
          <div
            style={{
              padding: "20px",
              textAlign: "center",
              color: "var(--secondary-text-color)",
              fontStyle: "italic",
              border: "2px dashed var(--border-color)",
              borderRadius: 4,
              background: "var(--panel-bg)",
              margin: "4px 0",
            }}
          >
            Drag paragraphs here to build your final letter
          </div>
        ) : (
          finalParagraphs
            .map((p, idx) => {
              if (!p || typeof p !== "object") {
                console.warn("Invalid paragraph at index:", idx, p);
                return null;
              }

              const paragraphVendor = p.vendor;
              const paragraphColor = paragraphVendor
                ? vendorColors[paragraphVendor] || "var(--header-bg)"
                : "var(--bg-color)";
              const tState = translationStates[p.id] || { viewLanguage: "source", translations: {} };

              return (
                <div key={p.id || `paragraph-${idx}`}>
                  <div data-paragraph-index={idx}>
                    <Paragraph
                      paragraph={p}
                      index={idx}
                      moveParagraph={moveFinalParagraph}
                      color={paragraphColor}
                      editable
                      keyTerms={requirements}
                      selectedKeyTerm={selectedKeyTerm}
                      translations={tState.translations}
                      viewLanguage={tState.viewLanguage}
                      onTranslationLoaded={(lang, text) => {
                        setTranslationStates((prev) => ({
                          ...prev,
                          [p.id]: {
                            ...(prev[p.id] || {}),
                            viewLanguage: lang,
                            translations: {
                              ...(prev[p.id]?.translations || {}),
                              [lang]: text,
                            },
                          },
                        }));
                      }}
                      onViewLanguageChange={(lang) => {
                        setTranslationStates((prev) => ({
                          ...prev,
                          [p.id]: {
                            ...(prev[p.id] || { translations: {} }),
                            viewLanguage: lang,
                          },
                        }));
                      }}
                      onTextChange={(txt) => updateParagraphText(idx, txt)}
                      onFragmentSplit={(index, fragments) => {
                        try {
                          handleFragmentSplit(index, fragments, p.text);
                        } catch (error) {
                          console.error("Error in fragment split callback:", error);
                        }
                      }}
                      onDelete={() => deleteParagraph(idx)}
                      onReorderUp={() => moveFinalParagraph(idx, idx - 1)}
                      onReorderDown={() => moveFinalParagraph(idx, idx + 1)}
                      reorderUpDisabled={idx <= 0}
                      reorderDownDisabled={idx >= finalParagraphs.length - 1}
                      languages={languageOptions}
                    />
                  </div>
                  <PlusButton onClick={() => addNewParagraph(idx + 1)} />
                </div>
              );
            })
            .filter(Boolean)
        )}
      </div>

      <div
        ref={bottomDrop}
        style={{
          minHeight: "50px",
          padding: "12px",
          textAlign: "center",
          color: isBottomOver ? "#007acc" : "var(--secondary-text-color)",
          border: isBottomOver ? "2px dashed #007acc" : "2px dashed var(--border-color)",
          borderRadius: "0 0 4px 4px",
          background: isBottomOver ? "var(--header-bg)" : "var(--panel-bg)",
          fontSize: "12px",
          transition: "all 0.2s ease",
          flexShrink: 0,
          cursor: "pointer",
        }}
        onMouseEnter={(e) => {
          if (!isBottomOver) {
            e.target.style.background = "var(--header-bg)";
            e.target.style.borderColor = "#007acc";
            e.target.style.color = "#007acc";
          }
        }}
        onMouseLeave={(e) => {
          if (!isBottomOver) {
            e.target.style.background = "var(--panel-bg)";
            e.target.style.borderColor = "var(--border-color)";
            e.target.style.color = "var(--secondary-text-color)";
          }
        }}
        onClick={() => addParagraphAtPosition({ text: "", vendor: null }, finalParagraphs.length)}
      >
        Drop here to add to bottom
      </div>
    </div>
  );
}
