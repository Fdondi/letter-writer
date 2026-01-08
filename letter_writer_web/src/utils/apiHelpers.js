/**
 * Common API helper utilities for handling responses, including 202 heartbeat handling
 */

/**
 * Fetches from an API endpoint and handles 202 Accepted (heartbeat) and 410 Gone (session restore) responses.
 * 
 * @param {string} url - The API endpoint URL
 * @param {RequestInit} options - Fetch options (method, headers, body, etc.)
 * @param {Object} restoreConfig - Optional config for session restoration
 *   - getState: Function to get current state object for restoration
 *   - maxRetries: Maximum number of restore retries (default: 1)
 * @returns {Promise<{status: number, data: any, isHeartbeat: boolean}>}
 *   - status: HTTP status code
 *   - data: Parsed JSON response (or heartbeat message if 202)
 *   - isHeartbeat: true if response was 202 (heartbeat), false otherwise
 * @throws {Error} If the response is not ok and not 202/410, or if restore fails
 */
export async function fetchWithHeartbeat(url, options = {}, restoreConfig = null) {
  const res = await fetch(url, options);
  
  // Handle 202 Accepted (heartbeat/still processing)
  if (res.status === 202) {
    const json = await res.json();
    // Request is still processing - this is a heartbeat/duplicate response
    // The original request is still in flight and will complete separately
    console.log(`Request still processing (heartbeat): ${url}`, json);
    return {
      status: res.status,
      data: json,
      isHeartbeat: true,
    };
  }
  
  // Handle 410 Gone (session lost - needs restore)
  if (res.status === 410) {
    const text = await res.text();
    let errorData = { detail: `Session lost: ${url}` };
    try {
      errorData = JSON.parse(text);
    } catch {
      // Not JSON, use text as detail
      errorData = { detail: text };
    }
    
    // Check if server is asking for restore
    if (errorData.requires_restore && restoreConfig && restoreConfig.getState) {
      console.log("Session lost detected, attempting restore...", errorData);
      
      try {
        // Import restore utilities
        const { syncStateToServer } = await import("./localState.js");
        
        // Get current state and restore to server
        const state = restoreConfig.getState();
        const restored = await syncStateToServer(state);
        
        if (!restored) {
          throw new Error("Failed to restore session to server");
        }
        
        console.log("Session restored successfully, retrying original request...");
        
        // Retry the original request (only once to avoid infinite loops)
        const maxRetries = restoreConfig.maxRetries || 1;
        if (maxRetries > 0) {
          return fetchWithHeartbeat(url, options, { ...restoreConfig, maxRetries: maxRetries - 1 });
        }
      } catch (restoreError) {
        console.error("Failed to restore session:", restoreError);
        throw new Error(`Session lost and restore failed: ${restoreError.message || restoreError}`);
      }
    }
    
    // If no restore config or restore failed, throw error
    throw new Error(errorData.detail || `Session lost: ${url}`);
  }
  
  if (!res.ok) {
    const text = await res.text();
    let detail = `Failed to fetch from ${url}`;
    try {
      const json = JSON.parse(text);
      detail = json.detail || json.message || text;
    } catch {
      detail = text || detail;
    }
    throw new Error(detail);
  }
  
  const data = await res.json();
  return {
    status: res.status,
    data,
    isHeartbeat: false,
  };
}

/**
 * Generic retry function for API calls.
 * Takes a URL, request body, and result handler - no phase knowledge.
 * 
 * @param {string} url - The API endpoint URL
 * @param {Object} body - The request body data
 * @param {Function} onResult - Callback function to handle the result: (data) => void
 * @returns {Promise<void>}
 * @throws {Error} If the API call fails
 */
export async function retryApiCall(url, body, onResult) {
  const result = await fetchWithHeartbeat(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  // Handle 202 Accepted (heartbeat/still processing)
  if (result.isHeartbeat) {
    // Don't throw error - request is still in progress
    return;
  }

  // Call the result handler with the data
  if (onResult) {
    onResult(result.data);
  }
}
