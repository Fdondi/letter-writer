import React, { useState, useRef, useEffect } from "react";
import { useDrag, useDrop } from "react-dnd";
import { HoverContext } from "../contexts/HoverContext";
import { v4 as uuidv4 } from "uuid";

export const ItemTypes = {
  PARAGRAPH: "paragraph",
};

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
  dropZoneRef = null
}) {
  const ref = useRef(null);
  const { hoverId, setHoverId } = React.useContext(HoverContext);
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(paragraph.text);

  // Drop zone for reordering within final column
  const [, drop] = useDrop(() => ({
    accept: ItemTypes.PARAGRAPH,
    hover(item, monitor) {
      if (!moveParagraph) return;
      if (item.index === index) return;
      
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
  }), [index, moveParagraph]);

  // Drag functionality
  const [{ isDragging }, drag] = useDrag({
    type: ItemTypes.PARAGRAPH,
    item: () => ({
      paragraph: {
        ...paragraph,
        sourceId: paragraph.sourceId || paragraph.id
      },
      index
    }),
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
    handleTextChange(editText);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      handleBlur();
    }
    if (e.key === 'Escape') {
      setEditText(paragraph.text);
      setIsEditing(false);
    }
  };

  // Update edit text when paragraph changes
  useEffect(() => {
    setEditText(paragraph.text);
  }, [paragraph.text]);

  const idleBg = color?.replace(/hsl\(([^)]+)\)/, "hsla($1,0.3)") || "#f0f0f0";
  const activeBg = color || "#e0e0e0";
  
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
        cursor: "move",
        marginBottom: 4,
        border: paragraph.isFragment ? "1px dashed #999" : "1px solid transparent",
        position: "relative",
        transition: "all 0.2s ease"
      }}
      onMouseEnter={() => setHoverId(sourceId)}
      onMouseLeave={() => setHoverId(null)}
    >
      {paragraph.isFragment && (
        <div style={{
          position: "absolute",
          top: -8,
          right: 4,
          fontSize: "10px",
          background: color || "#ddd",
          padding: "1px 4px",
          borderRadius: 2,
          color: "#666"
        }}>
          fragment
        </div>
      )}
      
      {editable ? (
        isEditing ? (
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            style={{
              width: "100%",
              minHeight: "60px",
              resize: "vertical",
              border: "1px solid #ddd",
              borderRadius: 2,
              padding: 4,
              fontFamily: "inherit",
              fontSize: "inherit",
              outline: "2px solid #007acc"
            }}
            autoFocus
          />
        ) : (
          <div
            onClick={() => setIsEditing(true)}
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
        <div style={{ whiteSpace: "pre-wrap", userSelect: "none" }}>
          {paragraph.text}
        </div>
      )}
    </div>
  );
} 