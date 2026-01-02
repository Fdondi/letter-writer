/**
 * Common API helper utilities for handling responses, including 202 heartbeat handling
 */

/**
 * Fetches from an API endpoint and handles 202 Accepted (heartbeat) responses consistently.
 * 
 * @param {string} url - The API endpoint URL
 * @param {RequestInit} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise<{status: number, data: any, isHeartbeat: boolean}>}
 *   - status: HTTP status code
 *   - data: Parsed JSON response (or heartbeat message if 202)
 *   - isHeartbeat: true if response was 202 (heartbeat), false otherwise
 * @throws {Error} If the response is not ok and not 202
 */
export async function fetchWithHeartbeat(url, options = {}) {
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
