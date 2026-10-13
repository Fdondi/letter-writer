import React from "react";
import { render, screen } from "@testing-library/react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { FLOW_LEAVE_PROMPT, useFlowHistoryGuard } from "../useFlowHistoryGuard";

function GuardedFlow({ onLeave }) {
  useFlowHistoryGuard({ enabled: true, onLeave });
  return <div>vendor flow</div>;
}

function renderGuard(onLeave) {
  window.history.pushState({ idx: 0 }, "", "/flows/vendors");
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="/flows/vendors" element={<GuardedFlow onLeave={onLeave} />} />
        <Route path="/" element={<div>job details</div>} />
      </Routes>
    </BrowserRouter>
  );
}

describe("useFlowHistoryGuard", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("keeps the flow mounted when browser back is cancelled", () => {
    jest.spyOn(window, "confirm").mockReturnValue(false);
    const onLeave = jest.fn();
    const bubble = jest.fn();
    window.addEventListener("popstate", bubble);
    renderGuard(onLeave);

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(window.confirm).toHaveBeenCalledWith(FLOW_LEAVE_PROMPT);
    expect(onLeave).not.toHaveBeenCalled();
    expect(bubble).not.toHaveBeenCalled();
    expect(screen.getByText("vendor flow")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/flows/vendors");
    window.removeEventListener("popstate", bubble);
  });

  it("leaves only after the back gesture is confirmed", () => {
    jest.spyOn(window, "confirm").mockReturnValue(true);
    const onLeave = jest.fn();
    renderGuard(onLeave);

    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(onLeave).toHaveBeenCalledTimes(1);
    expect(screen.getByText("vendor flow")).toBeInTheDocument();
  });
});
