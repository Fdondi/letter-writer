import '@testing-library/jest-dom';

// Runtime app version is fetched from public/app-version.txt; stub for Jest (no dev server).
const __origFetch = global.fetch;
global.fetch = jest.fn((input, init) => {
  const url = typeof input === 'string' ? input : input?.url ?? '';
  if (String(url).includes('app-version.txt')) {
    return Promise.resolve({
      ok: true,
      text: () => Promise.resolve('1.0.0'),
    });
  }
  if (String(url).includes('/api/personal-data/')) {
    return Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve({
          default_languages: [
            { code: 'en', label: 'English', color: '#3b82f6', enabled: true },
            { code: 'de', label: 'German', color: '#6366f1', enabled: true },
          ],
        }),
    });
  }
  if (typeof __origFetch === 'function') {
    return __origFetch(input, init);
  }
  return Promise.reject(new Error(`Unmocked fetch: ${url}`));
});

// Mock UUID to make tests deterministic
jest.mock('uuid', () => ({
  v4: jest.fn(() => 'test-uuid-123')
}));

// Mock window.navigator.clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn(() => Promise.resolve()),
  },
});

// Mock getBoundingClientRect for drag and drop tests
Element.prototype.getBoundingClientRect = jest.fn(() => ({
  width: 100,
  height: 50,
  top: 0,
  left: 0,
  bottom: 50,
  right: 100,
  x: 0,
  y: 0,
  toJSON: jest.fn()
}));

// Silence console warnings during tests unless they're specifically being tested
const originalConsoleWarn = console.warn;
console.warn = (...args) => {
  if (args[0]?.includes?.('Invalid') || args[0]?.includes?.('No item found')) {
    // Allow our validation warnings through during tests
    originalConsoleWarn(...args);
  }
  // Suppress other warnings during tests
};

