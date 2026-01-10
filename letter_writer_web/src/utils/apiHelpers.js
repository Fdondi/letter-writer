/**
 * Common API helper utilities for handling responses, including 202 heartbeat handling and CSRF protection
 */

// Cache CSRF token to avoid fetching it on every request
let csrfToken = null;

/**
 * Get CSRF token from server or cookie.
 * 
 * @returns {Promise<string>} CSRF token
 */
export async function getCsrfToken() {
  // Try to get from cookie first (Django sets csrftoken cookie)
  if (typeof document !== 'undefined') {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      if (name === 'csrftoken' && value) {
        csrfToken = value;
        return value;
      }
    }
  }
  
  // If not in cookie, fetch from API
  if (!csrfToken) {
    try {
      const response = await fetch('/api/auth/csrf-token/');
      if (response.ok) {
        const data = await response.json();
        csrfToken = data.csrfToken;
        return csrfToken;
      }
    } catch (e) {
      console.warn('Failed to fetch CSRF token:', e);
    }
  }
  
  return csrfToken || '';
}

/**
 * Initialize CSRF token on app load.
 * Call this once when the app starts to pre-fetch the CSRF token.
 * 
 * @returns {Promise<void>}
 */
export async function initializeCsrfToken() {
  try {
    await getCsrfToken();
  } catch (e) {
    console.warn('Failed to initialize CSRF token:', e);
  }
}

/**
 * Prepare fetch options with CSRF token and proper headers.
 * 
 * @param {RequestInit} options - Original fetch options
 * @returns {Promise<RequestInit>} Options with CSRF token added
 */
async function prepareOptions(options = {}) {
  const token = await getCsrfToken();
  
  // Merge headers
  const headers = {
    ...options.headers,
  };
  
  // Only set Content-Type to application/json if body is not FormData
  // FormData needs to set its own Content-Type with boundary
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json';
  }
  
  // Add CSRF token for state-changing requests (POST, PUT, DELETE, PATCH)
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method) && token) {
    headers['X-CSRFToken'] = token;
  }
  
  return {
    ...options,
    credentials: 'include', // Include cookies for CSRF and session
    headers,
  };
}

/**
 * Fetches from an API endpoint and handles 202 Accepted (heartbeat) and 410 Gone (session restore) responses.
 * Automatically includes CSRF token for state-changing requests.
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
  // Prepare options with CSRF token
  const preparedOptions = await prepareOptions(options);
  
  const res = await fetch(url, preparedOptions);
  
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
  
  // Handle 401 Unauthorized (authentication required)
  if (res.status === 401) {
    // Redirect to login page if not already there
    if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
      // Store the current path to redirect back after login
      const returnUrl = window.location.pathname + window.location.search;
      window.location.href = `/login?return=${encodeURIComponent(returnUrl)}`;
      // Return a rejected promise to stop further processing
      return Promise.reject(new Error('Unauthorized: Redirecting to login'));
    }
    // If already on login page, parse error message
    const text = await res.text();
    let errorData = { detail: 'Authentication required' };
    try {
      errorData = JSON.parse(text);
    } catch {
      errorData = { detail: text || 'Authentication required' };
    }
    throw new Error(errorData.detail || 'Authentication required');
  }
  
  // Handle 403 Forbidden (CSRF token missing or invalid)
  if (res.status === 403) {
    const text = await res.text();
    let errorData = { detail: `CSRF token missing or invalid: ${url}` };
    try {
      errorData = JSON.parse(text);
    } catch {
      // Not JSON, use text as detail
      errorData = { detail: text };
    }
    
    // Try to refresh CSRF token and retry once
    if (!csrfToken || errorData.detail?.toLowerCase().includes('csrf')) {
      console.warn('CSRF token invalid, refreshing and retrying...');
      csrfToken = null; // Clear cache
      try {
        const refreshedOptions = await prepareOptions(options);
        const retryRes = await fetch(url, refreshedOptions);
        
        // If retry still fails, throw error
        if (!retryRes.ok && retryRes.status === 403) {
          throw new Error(errorData.detail || 'CSRF validation failed. Please refresh the page.');
        }
        
        // Continue with retry response
        const retryText = await retryRes.text();
        if (retryRes.status === 202) {
          const retryJson = JSON.parse(retryText);
          return {
            status: retryRes.status,
            data: retryJson,
            isHeartbeat: true,
          };
        }
        if (retryRes.status === 410) {
          // Handle 410 on retry
          const retryErrorData = JSON.parse(retryText);
          throw new Error(retryErrorData.detail || `Session lost: ${url}`);
        }
        if (!retryRes.ok) {
          throw new Error(JSON.parse(retryText).detail || `Request failed: ${url}`);
        }
        const retryData = JSON.parse(retryText);
        return {
          status: retryRes.status,
          data: retryData,
          isHeartbeat: false,
        };
      } catch (retryError) {
        throw new Error(errorData.detail || `CSRF validation failed: ${retryError.message || retryError}`);
      }
    }
    
    throw new Error(errorData.detail || 'CSRF validation failed. Please refresh the page.');
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
  const result = await fetchWithHeartbeat(
    url,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
    null // No restore config for retry
  );

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
