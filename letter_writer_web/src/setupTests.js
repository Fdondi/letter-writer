import '@testing-library/jest-dom';

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

