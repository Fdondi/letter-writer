import React, { useState } from "react";

export const HoverContext = React.createContext({ hoverId: null, setHoverId: () => {} });

export function HoverProvider({ children }) {
  const [hoverId, setHoverId] = useState(null);
  return (
    <HoverContext.Provider value={{ hoverId, setHoverId }}>
      {children}
    </HoverContext.Provider>
  );
} 