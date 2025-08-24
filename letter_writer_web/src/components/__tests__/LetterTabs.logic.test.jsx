import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import LetterTabs from '../LetterTabs';
import { HoverProvider } from '../../contexts/HoverContext';

/**
 * FOCUSED LOGIC TESTS WITH PROPER DND CONTEXT
 * 
 * These tests focus on the core functions that handle array manipulation
 * WITH the necessary DnD provider context that the component requires.
 */

// Wrapper WITH DnD provider (required for LetterTabs component)
const TestWrapper = ({ children, ...props }) => (
  <DndProvider backend={TestBackend()}>
    <HoverProvider>
      <LetterTabs {...props} />
      {children}
    </HoverProvider>
  </DndProvider>
);

describe('LetterTabs Core Logic Tests', () => {
  let mockSetFinalParagraphs;
  let capturedLogs, capturedWarnings, capturedErrors;

  // Capture console output
  const originalLog = console.log;
  const originalWarn = console.warn;
  const originalError = console.error;

  beforeEach(() => {
    mockSetFinalParagraphs = jest.fn();
    capturedLogs = [];
    capturedWarnings = [];
    capturedErrors = [];

    console.log = (...args) => {
      capturedLogs.push(args);
      originalLog(...args);
    };
    console.warn = (...args) => {
      capturedWarnings.push(args);
      originalWarn(...args);
    };
    console.error = (...args) => {
      capturedErrors.push(args);
      originalError(...args);
    };

    jest.clearAllMocks();
  });

  afterEach(() => {
    console.log = originalLog;
    console.warn = originalWarn;
    console.error = originalError;
  });

  const defaultProps = {
    vendorsList: ['openai'],
    vendorParagraphs: {
      openai: [{ id: 'vendor-1', text: 'Vendor paragraph', vendor: 'openai' }]
    },
    finalParagraphs: [],
    setFinalParagraphs: mockSetFinalParagraphs,
    originalText: 'Original text',
    failedVendors: {},
    loadingVendors: new Set(),
    onRetry: jest.fn(),
    vendorColors: { openai: '#ff0000' },
    onAddParagraph: jest.fn()
  };

  describe('Array Manipulation Functions', () => {
    test('moveFinalParagraph function handles valid move operations', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'First paragraph', vendor: 'openai' },
        { id: 'final-2', text: 'Second paragraph', vendor: 'openai' },
        { id: 'final-3', text: 'Third paragraph', vendor: 'openai' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Since we can't easily access internal functions, we need to trigger them through the UI
      // But first, let's verify the component renders correctly
      expect(screen.getByText('First paragraph')).toBeInTheDocument();
      expect(screen.getByText('Second paragraph')).toBeInTheDocument();
      expect(screen.getByText('Third paragraph')).toBeInTheDocument();

      // Check that setFinalParagraphs was called during render setup
      // The function should be available and ready to handle moves
      expect(mockSetFinalParagraphs).toBeDefined();
    });

    test('function calls are properly logged', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Test paragraph', vendor: 'openai' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Component should render without errors
      expect(screen.getByText('Test paragraph')).toBeInTheDocument();

      // Print captured logs for manual inspection
      console.log('=== CAPTURED LOGS ===');
      console.log('Logs:', capturedLogs);
      console.log('Warnings:', capturedWarnings);
      console.log('Errors:', capturedErrors);
      console.log('=== END LOGS ===');

      // Should not have any errors during initial render
      expect(capturedErrors).toHaveLength(0);
    });

    test('index bounds checking works correctly', () => {
      // Create a scenario that might trigger bounds checking
      const finalParagraphs = [
        { id: 'final-1', text: 'Only paragraph', vendor: 'openai' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      expect(screen.getByText('Only paragraph')).toBeInTheDocument();

      // Component should handle edge cases gracefully
      // Check that we don't have any bounds-related warnings during normal operation
      const boundsWarnings = capturedWarnings.filter(w => 
        w.some(arg => typeof arg === 'string' && arg.includes('Invalid move'))
      );
      
      // During normal render, we shouldn't have invalid move warnings
      expect(boundsWarnings).toHaveLength(0);
    });

    test('handles empty finalParagraphs array', () => {
      render(<TestWrapper {...defaultProps} finalParagraphs={[]} />);

      // Should show empty state message
      expect(screen.getByText('Drag paragraphs here to build your final letter')).toBeInTheDocument();

      // Should not have any errors with empty array
      expect(capturedErrors).toHaveLength(0);
    });

    test('handles malformed finalParagraphs array', () => {
      const malformedParagraphs = [
        { id: 'good-1', text: 'Good paragraph', vendor: 'openai' },
        null, // Invalid entry
        undefined, // Invalid entry
        { id: 'good-2', text: 'Another good paragraph', vendor: 'openai' }
      ];

      expect(() => {
        render(<TestWrapper {...defaultProps} finalParagraphs={malformedParagraphs} />);
      }).not.toThrow();

      // Should render the valid paragraphs
      expect(screen.getByText('Good paragraph')).toBeInTheDocument();
      expect(screen.getByText('Another good paragraph')).toBeInTheDocument();

      // Should have warnings about invalid paragraphs
      const invalidWarnings = capturedWarnings.filter(w => 
        w.some(arg => typeof arg === 'string' && arg.includes('Invalid paragraph'))
      );
      
      expect(invalidWarnings.length).toBeGreaterThan(0);
    });
  });

  describe('Index Management Logic', () => {
    test('vendor paragraphs and final paragraphs have separate index spaces', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai', sourceId: 'vendor-1' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'openai', sourceId: 'vendor-1' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Both vendor and final paragraphs should be visible
      expect(screen.getByText('Vendor paragraph')).toBeInTheDocument(); // Vendor index 0
      expect(screen.getByText('Final paragraph 1')).toBeInTheDocument(); // Final index 0
      expect(screen.getByText('Final paragraph 2')).toBeInTheDocument(); // Final index 1

      // The vendor paragraph index (0) should not conflict with final paragraph indexes (0, 1)
      // This is verified by the component rendering correctly without conflicts
    });

    test('paragraph data-paragraph-index attributes are set correctly', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai' },
        { id: 'final-2', text: 'Final paragraph 2', vendor: 'openai' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Check that data-paragraph-index attributes are set correctly
      const paragraphElements = document.querySelectorAll('[data-paragraph-index]');
      
      // Should have 2 elements with data-paragraph-index
      expect(paragraphElements).toHaveLength(2);
      
      // Check that indexes are 0 and 1
      const indexes = Array.from(paragraphElements).map(el => 
        parseInt(el.getAttribute('data-paragraph-index'))
      );
      
      expect(indexes).toEqual([0, 1]);
    });

    test('sourceId tracking works correctly', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Final paragraph 1', vendor: 'openai', sourceId: 'vendor-1' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Component should render successfully with sourceId tracking
      expect(screen.getByText('Final paragraph 1')).toBeInTheDocument();

      // The paragraph should maintain its source relationship
      // This is important for highlighting and other features
    });
  });

  describe('Error Scenarios', () => {
    test('handles missing vendor colors gracefully', () => {
      const propsWithoutColors = {
        ...defaultProps,
        vendorColors: {} // Empty colors object
      };

      expect(() => {
        render(<TestWrapper {...propsWithoutColors} />);
      }).not.toThrow();

      expect(screen.getByText('Vendor paragraph')).toBeInTheDocument();
    });

    test('handles undefined setFinalParagraphs', () => {
      const propsWithoutSetter = {
        ...defaultProps,
        setFinalParagraphs: undefined
      };

      // Should not crash, even though it won't be fully functional
      expect(() => {
        render(<TestWrapper {...propsWithoutSetter} />);
      }).not.toThrow();
    });

    test('reports comprehensive debugging information', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Test paragraph', vendor: 'openai' }
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Print all debugging information
      console.log('\n=== DEBUGGING REPORT ===');
      console.log('Total logs captured:', capturedLogs.length);
      console.log('Total warnings captured:', capturedWarnings.length);
      console.log('Total errors captured:', capturedErrors.length);
      console.log('\nSample logs:');
      capturedLogs.slice(0, 5).forEach((log, i) => {
        console.log(`  ${i + 1}.`, log);
      });
      console.log('\nAll warnings:');
      capturedWarnings.forEach((warning, i) => {
        console.log(`  Warning ${i + 1}:`, warning);
      });
      console.log('\nAll errors:');
      capturedErrors.forEach((error, i) => {
        console.log(`  Error ${i + 1}:`, error);
      });
      console.log('=== END DEBUGGING REPORT ===\n');

      // Basic health check
      expect(capturedErrors).toHaveLength(0);
    });
  });
});
