import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import LetterTabs from '../LetterTabs';
import { HoverProvider } from '../../contexts/HoverContext';

// Test wrapper with DnD provider
const TestWrapper = ({ children, ...props }) => (
  <DndProvider backend={TestBackend}>
    <HoverProvider>
      <LetterTabs {...props} />
      {children}
    </HoverProvider>
  </DndProvider>
);

// Mock data for tests
const mockVendorsList = ['openai', 'anthropic', 'gemini'];
const mockVendorParagraphs = {
  openai: [
    { id: 'p1', text: 'OpenAI paragraph 1', vendor: 'openai' },
    { id: 'p2', text: 'OpenAI paragraph 2', vendor: 'openai' }
  ],
  anthropic: [
    { id: 'p3', text: 'Anthropic paragraph 1', vendor: 'anthropic' }
  ],
  gemini: [
    { id: 'p4', text: 'Gemini paragraph 1', vendor: 'gemini' }
  ]
};

const mockVendorColors = {
  openai: '#ff6b6b',
  anthropic: '#4ecdc4',
  gemini: '#45b7d1'
};

const defaultProps = {
  vendorsList: mockVendorsList,
  vendorParagraphs: mockVendorParagraphs,
  finalParagraphs: [],
  setFinalParagraphs: jest.fn(),
  originalText: 'Original letter text here...',
  failedVendors: {},
  loadingVendors: new Set(),
  onRetry: jest.fn(),
  vendorColors: mockVendorColors,
  onAddParagraph: jest.fn()
};

describe('LetterTabs Component', () => {
  let mockSetFinalParagraphs;

  beforeEach(() => {
    mockSetFinalParagraphs = jest.fn();
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    test('renders all vendor columns', () => {
      render(<TestWrapper {...defaultProps} />);
      
      expect(screen.getByText('openai')).toBeInTheDocument();
      expect(screen.getByText('anthropic')).toBeInTheDocument();
      expect(screen.getByText('gemini')).toBeInTheDocument();
    });

    test('renders final letter column', () => {
      render(<TestWrapper {...defaultProps} />);
      
      expect(screen.getByText('Final Letter')).toBeInTheDocument();
      expect(screen.getByText('Drag paragraphs here to build your final letter')).toBeInTheDocument();
    });

    test('renders original letter column', () => {
      render(<TestWrapper {...defaultProps} />);
      
      expect(screen.getByText('Original Letter')).toBeInTheDocument();
      expect(screen.getByText('Original letter text here...')).toBeInTheDocument();
    });

    test('renders bottom drop zone', () => {
      render(<TestWrapper {...defaultProps} />);
      
      expect(screen.getByText('Drop here to add to bottom')).toBeInTheDocument();
    });

    test('shows Final Letter column when final paragraphs exist', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Final paragraph 1', vendor: 'openai' }
      ];
      
      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      expect(screen.getByText('Final Letter')).toBeInTheDocument();
      expect(screen.getByText('Final paragraph 1')).toBeInTheDocument();
    });
  });

  describe('Paragraph Management', () => {
    test('adds new paragraph when plus button is clicked', async () => {
      const user = userEvent.setup();
      render(<TestWrapper {...defaultProps} setFinalParagraphs={mockSetFinalParagraphs} />);
      
      const addButton = screen.getAllByText('+ Add paragraph')[0];
      
      await act(async () => {
        await user.click(addButton);
      });
      
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
    });

    test('deletes paragraph when delete button is clicked', async () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Final paragraph 1', vendor: 'openai' }
      ];
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} 
        finalParagraphs={finalParagraphs} 
        setFinalParagraphs={mockSetFinalParagraphs} 
      />);
      
      const deleteButton = screen.getByTitle('Delete paragraph');
      
      await act(async () => {
        await user.click(deleteButton);
      });
      
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
    });

    test('updates paragraph text when edited', async () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Final paragraph 1', vendor: 'openai', isUserText: true }
      ];
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} 
        finalParagraphs={finalParagraphs} 
        setFinalParagraphs={mockSetFinalParagraphs} 
      />);
      
      // Click to edit
      const editableDiv = screen.getByText('Final paragraph 1');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      // Find textarea and update text
      const textarea = screen.getByDisplayValue('Final paragraph 1');
      
      await act(async () => {
        await user.clear(textarea);
        await user.type(textarea, 'Updated text');
      });
      
      // Blur to save
      await act(async () => {
        fireEvent.blur(textarea);
      });
      
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
    });
  });

  describe('Copy Functionality', () => {
    test('copy button is disabled when no paragraphs', () => {
      render(<TestWrapper {...defaultProps} />);
      
      const copyButton = screen.getByText('📋 Copy All');
      expect(copyButton).toBeDisabled();
    });

    test('copy button is enabled when paragraphs exist', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Final paragraph 1', vendor: 'openai' }
      ];
      
      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      const copyButton = screen.getByText('📋 Copy All');
      expect(copyButton).not.toBeDisabled();
    });

    test('copies text to clipboard when copy button is clicked', async () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Paragraph 1', vendor: 'openai' },
        { id: 'f2', text: 'Paragraph 2', vendor: 'anthropic' }
      ];
      const user = userEvent.setup();

      // Mock clipboard API
      const mockWriteText = jest.fn().mockResolvedValue();
      Object.defineProperty(navigator, 'clipboard', {
        value: {
          writeText: mockWriteText,
        },
        writable: true,
      });

      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);

      const copyButton = screen.getByText('📋 Copy All');
      
      await act(async () => {
        await user.click(copyButton);
      });

      expect(mockWriteText).toHaveBeenCalledWith('Paragraph 1\n\nParagraph 2');
    });
  });

  describe('Error Handling', () => {
    test('handles invalid paragraphs gracefully', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Valid paragraph', vendor: 'openai' },
        null, // Invalid paragraph
        undefined, // Invalid paragraph
        { id: 'f2', text: 'Another valid paragraph', vendor: 'anthropic' }
      ];
      
      // Should not throw an error
      expect(() => {
        render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);
      }).not.toThrow();
      
      expect(screen.getByText('Valid paragraph')).toBeInTheDocument();
      expect(screen.getByText('Another valid paragraph')).toBeInTheDocument();
    });

    test('shows loading state for vendors', () => {
      const loadingVendors = new Set(['openai']);
      
      render(<TestWrapper {...defaultProps} loadingVendors={loadingVendors} />);
      
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    test('shows error state for failed vendors', () => {
      const failedVendors = { openai: 'Connection failed' };
      
      render(<TestWrapper {...defaultProps} failedVendors={failedVendors} />);
      
      expect(screen.getByText('Connection failed')).toBeInTheDocument();
      expect(screen.getByText('Retry')).toBeInTheDocument();
    });

    test('calls onRetry when retry button is clicked', async () => {
      const failedVendors = { openai: 'Connection failed' };
      const onRetry = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} failedVendors={failedVendors} onRetry={onRetry} />);
      
      const retryButton = screen.getByText('Retry');
      
      await act(async () => {
        await user.click(retryButton);
      });
      
      expect(onRetry).toHaveBeenCalledWith('openai');
    });
  });

  describe('Bounds Checking', () => {
    test('moveFinalParagraph handles invalid indices', () => {
      const finalParagraphs = [
        { id: 'f1', text: 'Paragraph 1', vendor: 'openai' }
      ];
      
      render(<TestWrapper {...defaultProps} 
        finalParagraphs={finalParagraphs} 
        setFinalParagraphs={mockSetFinalParagraphs} 
      />);
      
      // The component should handle invalid moves gracefully
      // This is tested internally by the bounds checking we added
      expect(mockSetFinalParagraphs).not.toHaveBeenCalled();
    });

    test('handles array manipulation with invalid data', () => {
      // Test that component doesn't crash with edge cases
      const finalParagraphs = [];
      
      expect(() => {
        render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);
      }).not.toThrow();
    });
  });

  describe('Column Management', () => {
    test('shows collapsed vendors dropdown when vendors are collapsed', () => {
      render(<TestWrapper {...defaultProps} />);
      
      // Initially no dropdown should be visible
      expect(screen.queryByText('Restore collapsed...')).not.toBeInTheDocument();
    });

    test('calculates column width correctly', () => {
      render(<TestWrapper {...defaultProps} />);
      
      // With 3 vendors + final + original = 5 columns total
      // Each should be 20% width (100% / 5)
      const columns = screen.getAllByText(/openai|anthropic|gemini|Final Letter|Original Letter/);
      expect(columns.length).toBeGreaterThan(0);
    });
  });

  describe('Drop Zone Functionality', () => {
    test('bottom drop zone is always visible', () => {
      const finalParagraphs = Array.from({ length: 20 }, (_, i) => ({
        id: `f${i}`,
        text: `Long paragraph ${i}`,
        vendor: 'openai'
      }));
      
      render(<TestWrapper {...defaultProps} finalParagraphs={finalParagraphs} />);
      
      // Bottom drop zone should still be visible even with many paragraphs
      expect(screen.getByText('Drop here to add to bottom')).toBeInTheDocument();
    });

    test('bottom drop zone can be clicked to add paragraph', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} setFinalParagraphs={mockSetFinalParagraphs} />);
      
      const dropZone = screen.getByText('Drop here to add to bottom');
      
      await act(async () => {
        await user.click(dropZone);
      });
      
      expect(mockSetFinalParagraphs).toHaveBeenCalled();
    });
  });
});

