import React from 'react';
import { render } from '@testing-library/react';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import { HoverProvider } from '../../contexts/HoverContext';

/**
 * Custom render function that includes all necessary providers for testing
 * components that use drag and drop and hover context
 */
export const renderWithProviders = (ui, options = {}) => {
  const backend = TestBackend();
  
  const AllProviders = ({ children }) => {
    return (
      <DndProvider backend={backend}>
        <HoverProvider>
          {children}
        </HoverProvider>
      </DndProvider>
    );
  };

  return {
    backend,
    ...render(ui, { wrapper: AllProviders, ...options })
  };
};

/**
 * Creates mock paragraph data for testing
 */
export const createMockParagraph = (overrides = {}) => ({
  id: 'test-paragraph-id',
  text: 'Test paragraph text',
  vendor: 'openai',
  sourceId: 'source-id',
  ...overrides
});

/**
 * Creates mock vendor paragraphs data for testing
 */
export const createMockVendorParagraphs = () => ({
  openai: [
    createMockParagraph({ id: 'p1', text: 'OpenAI paragraph 1', vendor: 'openai' }),
    createMockParagraph({ id: 'p2', text: 'OpenAI paragraph 2', vendor: 'openai' })
  ],
  anthropic: [
    createMockParagraph({ id: 'p3', text: 'Anthropic paragraph 1', vendor: 'anthropic' })
  ],
  gemini: [
    createMockParagraph({ id: 'p4', text: 'Gemini paragraph 1', vendor: 'gemini' })
  ]
});

/**
 * Creates mock vendor colors for testing
 */
export const createMockVendorColors = () => ({
  openai: '#ff6b6b',
  anthropic: '#4ecdc4',
  gemini: '#45b7d1'
});

/**
 * Creates default props for LetterTabs component testing
 */
export const createDefaultLetterTabsProps = (overrides = {}) => ({
  vendorsList: ['openai', 'anthropic', 'gemini'],
  vendorParagraphs: createMockVendorParagraphs(),
  finalParagraphs: [],
  setFinalParagraphs: jest.fn(),
  originalText: 'Original letter text here...',
  failedVendors: {},
  loadingVendors: new Set(),
  onRetry: jest.fn(),
  vendorColors: createMockVendorColors(),
  onAddParagraph: jest.fn(),
  ...overrides
});

/**
 * Simulates a drag and drop operation between two elements
 */
export const simulateDragDrop = (backend, sourceElement, targetElement) => {
  if (!backend || !sourceElement || !targetElement) {
    throw new Error('Missing required parameters for drag and drop simulation');
  }
  
  // Start dragging from source
  backend.simulateBeginDrag([sourceElement]);
  
  // Hover over target
  backend.simulateHover([targetElement]);
  
  // Drop on target
  backend.simulateDrop();
  
  // End drag operation
  backend.simulateEndDrag();
};

/**
 * Waits for a mock function to be called with specific arguments
 */
export const waitForMockCall = async (mockFn, expectedArgs = [], timeout = 1000) => {
  return new Promise((resolve, reject) => {
    const checkCall = () => {
      if (mockFn.mock.calls.length > 0) {
        const lastCall = mockFn.mock.calls[mockFn.mock.calls.length - 1];
        if (expectedArgs.length === 0 || JSON.stringify(lastCall) === JSON.stringify(expectedArgs)) {
          resolve(lastCall);
        }
      }
    };
    
    // Check immediately
    checkCall();
    
    // Set up interval to check periodically
    const interval = setInterval(checkCall, 10);
    
    // Set timeout
    setTimeout(() => {
      clearInterval(interval);
      reject(new Error(`Mock function was not called with expected arguments within ${timeout}ms`));
    }, timeout);
  });
};

/**
 * Creates a user text paragraph for testing
 */
export const createUserTextParagraph = (overrides = {}) => ({
  id: 'user-text-id',
  text: 'User created text',
  vendor: null,
  sourceId: null,
  isUserText: true,
  ...overrides
});

/**
 * Creates a fragment paragraph for testing
 */
export const createFragmentParagraph = (overrides = {}) => ({
  id: 'fragment-id',
  text: 'Fragment text',
  vendor: 'openai',
  sourceId: 'original-id',
  isFragment: true,
  originalText: 'Original paragraph text',
  ...overrides
});

/**
 * Asserts that a component renders without throwing errors
 */
export const expectNoErrors = (renderFn) => {
  expect(renderFn).not.toThrow();
};

/**
 * Creates a mock setFinalParagraphs function that captures state changes
 */
export const createMockStateSetter = () => {
  const calls = [];
  const mockFn = jest.fn((updater) => {
    if (typeof updater === 'function') {
      // Simulate state update with previous state
      const prevState = calls.length > 0 ? calls[calls.length - 1].result : [];
      const result = updater(prevState);
      calls.push({ updater, result, prevState });
      return result;
    } else {
      calls.push({ updater, result: updater, prevState: null });
      return updater;
    }
  });
  
  mockFn.getCalls = () => calls;
  mockFn.getLastResult = () => calls.length > 0 ? calls[calls.length - 1].result : null;
  
  return mockFn;
};

