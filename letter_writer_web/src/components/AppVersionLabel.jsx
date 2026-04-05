import React, { useEffect, useState } from "react";
import { fetchAppVersion } from "../appVersion";

export default function AppVersionLabel() {
  const [version, setVersion] = useState(null);

  useEffect(() => {
    const ac = new AbortController();
    fetchAppVersion(ac.signal)
      .then(setVersion)
      .catch(() => setVersion(null));
    return () => ac.abort();
  }, []);

  if (version == null || version === "") return null;

  return (
    <span
      aria-label={`Application version ${version}`}
      style={{
        fontSize: "12px",
        fontWeight: 400,
        color: "var(--secondary-text-color)",
        whiteSpace: "nowrap",
      }}
    >
      v{version}
    </span>
  );
}
