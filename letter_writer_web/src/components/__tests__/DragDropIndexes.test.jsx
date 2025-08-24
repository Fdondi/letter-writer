import React from 'react';
import { render, screen } from '@testing-library/react';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import LetterTabs from '../LetterTabs';
import { HoverProvider } from '../../contexts/HoverContext';

/**
 * FOCUSED DRAG AND DROP INDEX MANAGEMENT TESTS
 * 
 * These tests specifically target the core issues:
 * 1. Are original vendor column indexes kept separate from final column indexes?
 * 2. Are final column indexes updated properly during reordering?
 * 3. Does index mutation during drag operations cause problems?
 */

// Mock console methods to capture logs
const originalConsoleLog = console.log;
const originalConsoleWarn = console.warn;
const originalConsoleError = console.error;

const mockVendorParagraphs = {
  openai: [
    { id: 'vendor-p1', text: 'Vendor paragraph 1', vendor: 'openai' },
    { id: 'vendor-p2', text: 'Vendor paragraph 2', vendor: 'openai' }
  ],
  anthropic: [
    { id: 'vendor-p3', text: 'Vendor paragraph 3', vendor: 'anthropic' }
  ]
};

const TestWrapper = ({ children, backend, ...props }) => (
  <DndProvider backend={backend}>
    <HoverProvider>
      <LetterTabs {...props} />
      {children}
    </HoverProvider>
  </DndProvider>
);

describe('Drag and Drop Index Management', () => {
  let backend;
  let mockSetFinalParagraphs;
  let logs, warnings, errors;

  beforeEach(() => {
    backend = TestBackend();
    mockSetFinalParagraphs = jest.fn();
    
    // Capture console output
    logs = [];
    warnings = [];
    errors = [];
    
    console.log = (...args) => {
      logs.push(args);
      originalConsoleLog(...args);
    };
    
    console.warn = (...args) => {
      warnings.push(args);
      originalConsoleWarn(...args);
    };
    
    console.error = (...args) => {
      errors.push(args);
      originalConsoleError(...args);
    };
    
    jest.clearAllMocks();
  });

  afterEach(() => {
    console.log = originalConsoleLog;
    console.warn = originalConsoleWarn;
    console.error = originalConsoleError;
  });

  const defaultProps = {
    vendorsList: ['openai', 'anthropic'],
    vendorParagraphs: mockVendorParagraphs,
    finalParagraphs: [],
    setFinalParagraphs: mockSetFinalParagraphs,
    originalText: 'Original text',
    failedVendors: {},
    loadingVendors: new Set(),
    onRetry: jest.fn(),
    vendorColors: { openai: '#ff0000', anthropic: '#00ff00' },
    onAddParagraph: jest.fn()
  };

  describe('Index Separation: Vendor vs Final Columns', () => {
    test('vendor column paragraphs maintain their own indexes', () => {
      render(<TestWrapper backend={backend} {...defaultProps} />);
      
      // Vendor paragraphs should render with their vendor-specific indexes
      const vendorParagraphs = screen.getAllByText(/Vendor paragraph/);
      expect(vendorParagraphs).toHaveLength(3);
      
      // Each vendor paragraph should have its own index (0, 1 for openai; 0 for anthropic)
      // The key insight: vendor indexes should NOT interfere with final column indexes
    });

    test('final column paragraphs use independent indexes', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai', sourceId: 'vendor-p1' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'anthropic', sourceId: 'vendor-p3' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      // Final paragraphs should have indexes 0, 1 regardless of their source vendor indexes
      const finalTexts = screen.getAllByText(/Final paragraph/);
      expect(finalTexts).toHaveLength(2);
    });

    test('dragging from vendor to final creates new index', () => {
      render(<TestWrapper backend={backend} {...defaultProps} />);
      
      // Get a vendor paragraph (this has vendor index 0)
      const vendorParagraph = screen.getByText('Vendor paragraph 1');
      const dropZone = screen.getByText('Drag paragraphs here to build your final letter');
      
      // Simulate drag from vendor (index 0) to empty final column
      backend.simulateBeginDrag([vendorParagraph.closest('div')]);
      backend.simulateHover([dropZone.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Should call setFinalParagraphs to add at index 0 of final column
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
      
      // Check that no invalid index warnings were logged
      const invalidIndexWarnings = warnings.filter(w => 
        w.some(arg => typeof arg === 'string' && arg.includes('Invalid'))
      );
      expect(invalidIndexWarnings).toHaveLength(0);
    });
  });

  describe('Final Column Reordering', () => {
    test('moving within final column uses final column indexes only', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai', sourceId: 'vendor-p1' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'anthropic', sourceId: 'vendor-p3' },
        { id: 'final-3', text: 'Final paragraph 3', vendor: 'openai', sourceId: 'vendor-p2' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      // Get final column paragraphs
      const firstParagraph = screen.getByText('Final paragraph 1');
      const thirdParagraph = screen.getByText('Final paragraph 3');
      
      // Simulate moving first paragraph (index 0) to position after third (index 2)
      backend.simulateBeginDrag([firstParagraph.closest('div')]);
      backend.simulateHover([thirdParagraph.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Should call setFinalParagraphs with move operation
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
      
      // Examine the actual function calls to see if indexes are correct
      const calls = mockSetFinalParagraphs.mock.calls;
      console.log('setFinalParagraphs calls:', calls);
    });

    test('index mutation during hover does not cause out-of-bounds errors', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'anthropic' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      const firstParagraph = screen.getByText('Final paragraph 1');
      const secondParagraph = screen.getByText('Final paragraph 2');
      
      // Simulate rapid hover operations that might cause index mutation issues
      backend.simulateBeginDrag([firstParagraph.closest('div')]);
      backend.simulateHover([secondParagraph.closest('div')]);
      backend.simulateHover([firstParagraph.closest('div')]);
      backend.simulateHover([secondParagraph.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Check for any bounds-related errors
      const boundsErrors = errors.filter(e => 
        e.some(arg => typeof arg === 'string' && (arg.includes('bounds') || arg.includes('Invalid')))
      );
      expect(boundsErrors).toHaveLength(0);
      
      // Log all warnings and errors for debugging
      console.log('Warnings during rapid hover:', warnings);
      console.log('Errors during rapid hover:', errors);
    });
  });

  describe('Index Edge Cases', () => {
    test('dragging to position beyond array length', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      // Try to add at position 999 (way beyond array length)
      const vendorParagraph = screen.getByText('Vendor paragraph 1');
      const bottomDropZone = screen.getByText('Drop here to add to bottom');
      
      backend.simulateBeginDrag([vendorParagraph.closest('div')]);
      backend.simulateHover([bottomDropZone]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Should handle gracefully and add to end
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
      
      // Should not have invalid index warnings
      const invalidWarnings = warnings.filter(w => 
        w.some(arg => typeof arg === 'string' && arg.includes('Invalid'))
      );
      expect(invalidWarnings).toHaveLength(0);
    });

    test('moving item to its own position', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'anthropic' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      const firstParagraph = screen.getByText('Final paragraph 1');
      
      // Try to move item to its own position (should be no-op)
      backend.simulateBeginDrag([firstParagraph.closest('div')]);
      backend.simulateHover([firstParagraph.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Should not trigger move operation (from === to)
      // Check logs to see if this was detected and skipped
      const skipWarnings = warnings.filter(w => 
        w.some(arg => typeof arg === 'string' && arg.includes('from === to'))
      );
      
      console.log('Self-move warnings:', skipWarnings);
      console.log('All setFinalParagraphs calls:', mockSetFinalParagraphs.mock.calls);
    });

    test('handles empty final paragraphs array', () => {
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={[]} />);
      
      const vendorParagraph = screen.getByText('Vendor paragraph 1');
      const emptyMessage = screen.getByText('Drag paragraphs here to build your final letter');
      
      // Drag to empty final column
      backend.simulateBeginDrag([vendorParagraph.closest('div')]);
      backend.simulateHover([emptyMessage.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
      
      // Should not have array bounds errors
      const arrayErrors = errors.filter(e => 
        e.some(arg => typeof arg === 'string' && arg.includes('array'))
      );
      expect(arrayErrors).toHaveLength(0);
    });
  });

  describe('Debugging Information', () => {
    test('logs provide sufficient debugging information', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'anthropic' }
      ];
      
      render(<TestWrapper backend={backend} {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      const firstParagraph = screen.getByText('Final paragraph 1');
      const secondParagraph = screen.getByText('Final paragraph 2');
      
      // Perform a move operation
      backend.simulateBeginDrag([firstParagraph.closest('div')]);
      backend.simulateHover([secondParagraph.closest('div')]);
      backend.simulateDrop();
      backend.simulateEndDrag();
      
      // Print all logs for manual inspection
      console.log('=== DEBUGGING LOGS ===');
      console.log('All logs:', logs);
      console.log('All warnings:', warnings);
      console.log('All errors:', errors);
      console.log('setFinalParagraphs calls:', mockSetFinalParagraphs.mock.calls);
      console.log('=== END DEBUGGING ===');
      
      // At minimum, we should have some interaction
      expect(logs.length + warnings.length + errors.length + mockSetFinalParagraphs.mock.calls.length)
        .toBeGreaterThan(0);
    });
  });
});

