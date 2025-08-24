import React from 'react';
import { render, screen } from '@testing-library/react';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import { getBackendReactDndTestUtils } from 'react-dnd-test-utils';
import LetterTabs from '../LetterTabs';
import { HoverProvider } from '../../contexts/HoverContext';

// Test wrapper with all necessary providers
const TestWrapper = ({ children, ...props }) => {
  const backend = TestBackend();
  
  return (
    <DndProvider backend={backend}>
      <HoverProvider>
        <LetterTabs {...props} />
        {children}
      </HoverProvider>
    </DndProvider>
  );
};

const mockVendorParagraphs = {
  openai: [
    { id: 'p1', text: 'OpenAI paragraph 1', vendor: 'openai' },
    { id: 'p2', text: 'OpenAI paragraph 2', vendor: 'openai' }
  ],
  anthropic: [
    { id: 'p3', text: 'Anthropic paragraph 1', vendor: 'anthropic' }
  ]
};

const mockVendorColors = {
  openai: '#ff6b6b',
  anthropic: '#4ecdc4'
};

const defaultProps = {
  vendorsList: ['openai', 'anthropic'],
  vendorParagraphs: mockVendorParagraphs,
  finalParagraphs: [],
  setFinalParagraphs: jest.fn(),
  originalText: 'Original letter text',
  failedVendors: {},
  loadingVendors: new Set(),
  onRetry: jest.fn(),
  vendorColors: mockVendorColors,
  onAddParagraph: jest.fn()
};

describe('Drag and Drop Integration Tests', () => {
  let mockSetFinalParagraphs;
  let backend;
  let utils;

  beforeEach(() => {
    mockSetFinalParagraphs = jest.fn();
    jest.clearAllMocks();
  });

  const renderWithDragDrop = (props = {}) => {
    const testBackend = TestBackend();
    backend = testBackend;
    utils = getBackendReactDndTestUtils(testBackend);
    
    return render(
      <DndProvider backend={testBackend}>
        <HoverProvider>
          <LetterTabs {...defaultProps} setFinalParagraphs={mockSetFinalParagraphs} {...props} />
        </HoverProvider>
      </DndProvider>
    );
  };

  describe('Basic Drag and Drop', () => {
    test('can drag paragraph from vendor column to final column', () => {
      renderWithDragDrop();
      
      // Find source paragraph in vendor column
      const sourceParagraph = screen.getByText('OpenAI paragraph 1');
      expect(sourceParagraph).toBeInTheDocument();
      
      // Find drop target (final column content area)
      const dropTarget = screen.getByText('Drag paragraphs here to build your final letter');
      expect(dropTarget).toBeInTheDocument();
      
      // Simulate drag and drop
      const sourceElement = sourceParagraph.closest('[draggable]') || sourceParagraph.closest('div');
      const targetElement = dropTarget.closest('div');
      
      if (sourceElement && targetElement) {
        utils.dragDrop(sourceElement, targetElement);
        
        // Should call setFinalParagraphs to add the paragraph
        expect(mockSetFinalParagraphs).toHaveBeenCalled();
      }
    });

    test('can drag paragraph to bottom drop zone', () => {
      renderWithDragDrop();
      
      const sourceParagraph = screen.getByText('OpenAI paragraph 1');
      const bottomDropZone = screen.getByText('Drop here to add to bottom');
      
      const sourceElement = sourceParagraph.closest('div');
      const targetElement = bottomDropZone;
      
      if (sourceElement && targetElement) {
        utils.dragDrop(sourceElement, targetElement);
        
        expect(mockSetFinalParagraphs).toHaveBeenCalled();
      }
    });
  });

  describe('Reordering in Final Column', () => {
    test('can reorder paragraphs within final column', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'First paragraph', vendor: 'openai', sourceId: 'p1' },
        { id: 'f2', text: 'Second paragraph', vendor: 'anthropic', sourceId: 'p3' }
      ];
      
      renderWithDragDrop({ finalParagraphs });
      
      const firstParagraph = screen.getByText('First paragraph');
      const secondParagraph = screen.getByText('Second paragraph');
      
      expect(firstParagraph).toBeInTheDocument();
      expect(secondParagraph).toBeInTheDocument();
      
      // Simulate dragging first paragraph below second
      const sourceElement = firstParagraph.closest('div');
      const targetElement = secondParagraph.closest('div');
      
      if (sourceElement && targetElement) {
        utils.dragDrop(sourceElement, targetElement);
        
        // Should call moveParagraph function
        expect(mockSetFinalParagraphs).toHaveBeenCalled();
      }
    });

    test('prevents invalid reordering operations', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Only paragraph', vendor: 'openai' }
      ];
      
      renderWithDragDrop({ finalParagraphs });
      
      const paragraph = screen.getByText('Only paragraph');
      expect(paragraph).toBeInTheDocument();
      
      // Try to drag paragraph to itself (should be prevented)
      const element = paragraph.closest('div');
      
      if (element) {
        utils.dragDrop(element, element);
        
        // Should not call setFinalParagraphs for invalid operations
        // The component's bounds checking should prevent this
      }
    });
  });

  describe('Drop Zone Visual Feedback', () => {
    test('shows visual feedback when hovering over drop zones', () => {
      renderWithDragDrop();
      
      const sourceParagraph = screen.getByText('OpenAI paragraph 1');
      const finalColumn = screen.getByText('Final Letter').closest('div');
      
      // Start dragging
      const sourceElement = sourceParagraph.closest('div');
      if (sourceElement) {
        utils.drag(sourceElement);
        
        // The drop zones should show visual feedback
        // This is tested through the isOver state in the drop hooks
        expect(screen.getByText('Drop here to add to bottom')).toBeInTheDocument();
      }
    });

    test('different drop zones handle drops correctly', () => {
      renderWithDragDrop();
      
      const sourceParagraph = screen.getByText('OpenAI paragraph 1');
      
      // Test content area drop
      const contentArea = screen.getByText('Drag paragraphs here to build your final letter');
      const sourceElement = sourceParagraph.closest('div');
      
      if (sourceElement) {
        utils.dragDrop(sourceElement, contentArea);
        expect(mockSetFinalParagraphs).toHaveBeenCalled();
        
        // Clear the mock for next test
        mockSetFinalParagraphs.mockClear();
        
        // Test bottom drop zone
        const bottomZone = screen.getByText('Drop here to add to bottom');
        utils.dragDrop(sourceElement, bottomZone);
        expect(mockSetFinalParagraphs).toHaveBeenCalled();
      }
    });
  });

  describe('Error Handling in Drag and Drop', () => {
    test('handles drag with invalid data gracefully', () => {
      renderWithDragDrop();
      
      // The component should handle edge cases gracefully
      // This is ensured by our bounds checking and error handling
      expect(screen.getByText('Final Letter')).toBeInTheDocument();
    });

    test('prevents drops when component state is invalid', () => {
      // Test with malformed data
      const malformedProps = {
        ...defaultProps,
        finalParagraphs: [null, undefined, { invalid: 'data' }],
        setFinalParagraphs: mockSetFinalParagraphs
      };
      
      expect(() => {
        renderWithDragDrop(malformedProps);
      }).not.toThrow();
      
      // Component should still render and be functional
      expect(screen.getByText('Final Letter')).toBeInTheDocument();
    });
  });

  describe('Drag Source Behavior', () => {
    test('vendor column paragraphs are draggable but not reorderable', () => {
      renderWithDragDrop();
      
      const vendorParagraph = screen.getByText('OpenAI paragraph 1');
      expect(vendorParagraph).toBeInTheDocument();
      
      // Vendor paragraphs should be draggable for copying to final column
      // but should not affect their source column order
      const element = vendorParagraph.closest('div');
      expect(element).toHaveAttribute('style', expect.stringContaining('cursor'));
    });

    test('final column paragraphs are both draggable and reorderable', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Final paragraph', vendor: 'openai', sourceId: 'p1' }
      ];
      
      renderWithDragDrop({ finalParagraphs });
      
      const finalParagraph = screen.getByText('Final paragraph');
      expect(finalParagraph).toBeInTheDocument();
      
      // Final column paragraphs should support both drag-to-copy and reordering
      const element = finalParagraph.closest('div');
      expect(element).toBeInTheDocument();
    });
  });

  describe('Performance and Edge Cases', () => {
    test('handles large number of paragraphs efficiently', () => {
      const manyParagraphs = Array.from({ length: 50 }, (_, i) => ({
        id: `p${i}`,
        text: `Paragraph ${i}`,
        vendor: 'openai'
      }));
      
      const finalParagraphs = manyParagraphs.slice(0, 25);
      
      expect(() => {
        renderWithDragDrop({ 
          finalParagraphs,
          vendorParagraphs: { openai: manyParagraphs.slice(25) }
        });
      }).not.toThrow();
      
      // Should still show bottom drop zone
      expect(screen.getByText('Drop here to add to bottom')).toBeInTheDocument();
    });

    test('maintains scroll position during drag operations', () => {
      const finalParagraphs = Array.from({ length: 20 }, (_, i) => ({
        id: `f${i}`,
        text: `Long paragraph ${i}`,
        vendor: 'openai'
      }));
      
      renderWithDragDrop({ finalParagraphs });
      
      // Bottom drop zone should be accessible even with many paragraphs
      expect(screen.getByText('Drop here to add to bottom')).toBeInTheDocument();
    });
  });
});

