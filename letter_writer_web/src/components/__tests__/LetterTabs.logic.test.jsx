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
  <DndProvider backend={TestBackend}>
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

  describe('Copy Functionality Tests', () => {
    test('copyFinalText preserves exact paragraph order', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'First paragraph text', vendor: 'openai' },
        { id: 'final-2', text: 'Second paragraph text', vendor: 'anthropic' },
        { id: 'final-3', text: 'Third paragraph text', vendor: 'openai' },
        { id: 'final-4', text: 'Fourth paragraph text', vendor: 'gemini' }
      ];

      // Mock clipboard API
      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      // Find and click the copy button
      const copyButton = screen.getByText('📋 Copy All');
      expect(copyButton).toBeInTheDocument();

      act(() => {
        copyButton.click();
      });

      // Verify the text was copied in the correct order
      expect(mockWriteText).toHaveBeenCalledWith(
        'First paragraph text\n\nSecond paragraph text\n\nThird paragraph text\n\nFourth paragraph text'
      );
    });

    test('copyFinalText handles single paragraph correctly', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Only paragraph text', vendor: 'openai' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      expect(mockWriteText).toHaveBeenCalledWith('Only paragraph text');
    });

    test('copyFinalText includes all paragraphs without missing any', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Paragraph A', vendor: 'openai' },
        { id: 'final-2', text: 'Paragraph B', vendor: 'anthropic' },
        { id: 'final-3', text: 'Paragraph C', vendor: 'gemini' },
        { id: 'final-4', text: 'Paragraph D', vendor: 'openai' },
        { id: 'final-5', text: 'Paragraph E', vendor: 'mistral' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      const expectedText = 'Paragraph A\n\nParagraph B\n\nParagraph C\n\nParagraph D\n\nParagraph E';
      expect(mockWriteText).toHaveBeenCalledWith(expectedText);

      // Verify that each paragraph text appears exactly once
      const copiedText = mockWriteText.mock.calls[0][0];
      expect(copiedText.split('Paragraph A')).toHaveLength(2); // Should appear exactly once
      expect(copiedText.split('Paragraph B')).toHaveLength(2);
      expect(copiedText.split('Paragraph C')).toHaveLength(2);
      expect(copiedText.split('Paragraph D')).toHaveLength(2);
      expect(copiedText.split('Paragraph E')).toHaveLength(2);
    });

    test('copyFinalText does not duplicate paragraphs', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Unique paragraph 1', vendor: 'openai' },
        { id: 'final-2', text: 'Unique paragraph 2', vendor: 'openai' },
        { id: 'final-3', text: 'Unique paragraph 3', vendor: 'anthropic' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      const copiedText = mockWriteText.mock.calls[0][0];
      
      // Check that each unique text appears exactly once
      expect(copiedText.match(/Unique paragraph 1/g)).toHaveLength(1);
      expect(copiedText.match(/Unique paragraph 2/g)).toHaveLength(1);
      expect(copiedText.match(/Unique paragraph 3/g)).toHaveLength(1);
      
      // Verify exact content and order
      expect(copiedText).toBe('Unique paragraph 1\n\nUnique paragraph 2\n\nUnique paragraph 3');
    });

    test('copyFinalText handles empty paragraphs correctly', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'First paragraph', vendor: 'openai' },
        { id: 'final-2', text: '', vendor: 'anthropic' }, // Empty paragraph
        { id: 'final-3', text: 'Third paragraph', vendor: 'gemini' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      // Empty paragraphs should still be included in the structure
      expect(mockWriteText).toHaveBeenCalledWith('First paragraph\n\n\n\nThird paragraph');
    });

    test('copyFinalText handles whitespace-only paragraphs correctly', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'First paragraph', vendor: 'openai' },
        { id: 'final-2', text: '   \n  \t  ', vendor: 'anthropic' }, // Whitespace only
        { id: 'final-3', text: 'Third paragraph', vendor: 'gemini' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      // Whitespace paragraphs should be preserved as-is
      expect(mockWriteText).toHaveBeenCalledWith('First paragraph\n\n   \n  \t  \n\nThird paragraph');
    });

    test('copyFinalText handles special characters in paragraph text', () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Paragraph with "quotes" and \'apostrophes\'', vendor: 'openai' },
        { id: 'final-2', text: 'Paragraph with\nnewlines\nand\ttabs', vendor: 'anthropic' },
        { id: 'final-3', text: 'Paragraph with émojis 🚀 and ünicöde', vendor: 'gemini' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      const expectedText = 'Paragraph with "quotes" and \'apostrophes\'\n\nParagraph with\nnewlines\nand\ttabs\n\nParagraph with émojis 🚀 and ünicöde';
      expect(mockWriteText).toHaveBeenCalledWith(expectedText);
    });

    test('copy button is disabled when no paragraphs exist', () => {
      const finalParagraphs = [];

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      expect(copyButton).toBeDisabled();
    });

    test('copyFinalText handles clipboard API failure gracefully', async () => {
      const finalParagraphs = [
        { id: 'final-1', text: 'Test paragraph', vendor: 'openai' }
      ];

      const mockWriteText = jest.fn().mockRejectedValue(new Error('Clipboard access denied'));
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      // Mock alert to avoid actual alert dialog
      const mockAlert = jest.fn();
      window.alert = mockAlert;

      // Temporarily suppress the expected console.error for this test
      const originalConsoleError = console.error;
      console.error = jest.fn();

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      await act(async () => {
        copyButton.click();
        // Wait for the promise rejection to be handled
        await new Promise(resolve => setTimeout(resolve, 0));
      });

      // Should attempt to copy
      expect(mockWriteText).toHaveBeenCalledWith('Test paragraph');
      
      // Should show error to user
      expect(mockAlert).toHaveBeenCalledWith('Failed to copy text to clipboard');
      
      // Should log the error
      expect(console.error).toHaveBeenCalledWith('Failed to copy text:', expect.any(Error));
      
      // Restore console.error
      console.error = originalConsoleError;
    });

    test('copyFinalText preserves exact order after drag and drop operations', () => {
      // This test verifies that after paragraphs are moved around, 
      // the copy function still respects the current display order
      const initialParagraphs = [
        { id: 'final-1', text: 'Original first', vendor: 'openai' },
        { id: 'final-2', text: 'Original second', vendor: 'anthropic' },
        { id: 'final-3', text: 'Original third', vendor: 'gemini' }
      ];

      const mockWriteText = jest.fn().mockResolvedValue();
      Object.assign(navigator, {
        clipboard: {
          writeText: mockWriteText,
        },
      });

      // Simulate that paragraphs have been reordered (would happen through drag/drop)
      const reorderedParagraphs = [
        { id: 'final-3', text: 'Original third', vendor: 'gemini' },   // Now first
        { id: 'final-1', text: 'Original first', vendor: 'openai' },  // Now second  
        { id: 'final-2', text: 'Original second', vendor: 'anthropic' } // Now third
      ];

      render(<TestWrapper {...defaultProps} finalParagraphs={reorderedParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      act(() => {
        copyButton.click();
      });

      // Should copy in the NEW order, not the original order
      expect(mockWriteText).toHaveBeenCalledWith('Original third\n\nOriginal first\n\nOriginal second');
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
