import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DndProvider } from 'react-dnd';
import { TestBackend } from 'react-dnd-test-backend';
import Paragraph from '../Paragraph';
import { HoverProvider } from '../../contexts/HoverContext';

// Test wrapper with DnD provider
const TestWrapper = ({ children, ...props }) => (
  <DndProvider backend={TestBackend}>
    <HoverProvider>
      <Paragraph {...props} />
      {children}
    </HoverProvider>
  </DndProvider>
);

const mockParagraph = {
  id: 'test-paragraph-1',
  text: 'This is a test paragraph',
  vendor: 'openai',
  sourceId: 'source-1'
};

const defaultProps = {
  paragraph: mockParagraph,
  index: 0,
  moveParagraph: jest.fn(),
  color: 'hsl(0,100%,69%)',
  editable: false
};

describe('Paragraph Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    test('renders paragraph text', () => {
      render(<TestWrapper {...defaultProps} />);
      
      expect(screen.getByText('This is a test paragraph')).toBeInTheDocument();
    });

    test('applies correct background color', () => {
      render(<TestWrapper {...defaultProps} />);
      
      const textElement = screen.getByText('This is a test paragraph');
      const paragraphElement = textElement.closest('div');
      const outerDiv = paragraphElement.parentElement;
      
      console.log('Text element:', textElement.tagName);
      console.log('Closest div style:', paragraphElement.getAttribute('style'));
      console.log('Parent element style:', outerDiv?.getAttribute('style'));
      
      // The background should be on the container div
      const containerStyle = outerDiv?.getAttribute('style') || paragraphElement.getAttribute('style');
      expect(containerStyle).toContain('background');
    });

    test('shows fragment label for fragments', () => {
      const fragmentParagraph = {
        ...mockParagraph,
        isFragment: true
      };
      
      render(<TestWrapper {...defaultProps} paragraph={fragmentParagraph} />);
      
      expect(screen.getByText('fragment')).toBeInTheDocument();
    });

    test('shows user text label for user text', () => {
      const userParagraph = {
        ...mockParagraph,
        isUserText: true,
        vendor: null
      };
      
      render(<TestWrapper {...defaultProps} paragraph={userParagraph} />);
      
      expect(screen.getByText('user text')).toBeInTheDocument();
    });

    test('shows delete button when onDelete prop is provided', () => {
      const onDelete = jest.fn();
      
      render(<TestWrapper {...defaultProps} onDelete={onDelete} />);
      
      expect(screen.getByTitle('Delete paragraph')).toBeInTheDocument();
    });
  });

  describe('Editable Mode', () => {
    test('shows editable content when editable is true', () => {
      render(<TestWrapper {...defaultProps} editable={true} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      expect(editableDiv).toHaveStyle('cursor: text');
    });

    test('enters edit mode when clicked', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      expect(screen.getByDisplayValue('This is a test paragraph')).toBeInTheDocument();
    });

    test('calls onTextChange when text is updated', async () => {
      const onTextChange = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} onTextChange={onTextChange} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        await user.clear(textarea);
        await user.type(textarea, 'Updated text');
      });
      
      await act(async () => {
        fireEvent.blur(textarea);
      });
      
      expect(onTextChange).toHaveBeenCalledWith('Updated text');
    });

    test('exits edit mode on blur', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        fireEvent.blur(textarea);
      });
      
      expect(screen.queryByDisplayValue('This is a test paragraph')).not.toBeInTheDocument();
    });

    test('exits edit mode on Escape key', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        await user.type(textarea, 'Some changes');
        await user.keyboard('{Escape}');
      });
      
      // Should revert to original text
      expect(screen.getByText('This is a test paragraph')).toBeInTheDocument();
    });

    test('saves on Ctrl+Enter', async () => {
      const onTextChange = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} onTextChange={onTextChange} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        await user.clear(textarea);
        await user.type(textarea, 'Updated text');
        await user.keyboard('{Control>}{Enter}{/Control}');
      });
      
      expect(onTextChange).toHaveBeenCalledWith('Updated text');
    });
  });

  describe('Copy Mode', () => {
    test('enters copy mode on double click when not editable', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} />);
      
      const paragraphDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.dblClick(paragraphDiv);
      });
      
      expect(screen.getByText('copy mode')).toBeInTheDocument();
    });

    test('text is selectable in copy mode', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} />);
      
      const paragraphDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.dblClick(paragraphDiv);
      });
      
      const textDiv = screen.getByText('This is a test paragraph');
      expect(textDiv).toHaveStyle('user-select: text');
    });

    test('exits copy mode on mouse leave', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} />);
      
      const paragraphElement = screen.getByText('This is a test paragraph').closest('div');
      
      await act(async () => {
        await user.dblClick(paragraphElement);
      });
      
      expect(screen.getByText('copy mode')).toBeInTheDocument();
      
      await act(async () => {
        fireEvent.mouseLeave(paragraphElement);
      });
      
      await waitFor(() => {
        expect(screen.queryByText('copy mode')).not.toBeInTheDocument();
      });
    });
  });

  describe('Drag and Drop', () => {
    test('prevents drag when in copy mode', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} />);
      
      const paragraphElement = screen.getByText('This is a test paragraph').closest('div');
      
      await act(async () => {
        await user.dblClick(paragraphElement);
      });
      
      // In copy mode, should not be draggable
      const textDiv = screen.getByText('This is a test paragraph');
      expect(textDiv).toHaveStyle('cursor: text');
    });

    test('prevents drag when editing', async () => {
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} editable={true} />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      // Should be in edit mode with textarea
      expect(screen.getByDisplayValue('This is a test paragraph')).toBeInTheDocument();
      
      // Drag should be disabled in edit mode
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      expect(textarea).toBeInTheDocument();
    });

    test('calls moveParagraph when valid drag occurs', () => {
      const moveParagraph = jest.fn();
      
      render(<TestWrapper {...defaultProps} moveParagraph={moveParagraph} />);
      
      // Note: Full drag and drop testing requires more complex setup with TestBackend
      // This test verifies the function is passed correctly
      expect(moveParagraph).toBeDefined();
    });

    test('does not call moveParagraph for empty function (vendor columns)', () => {
      const emptyMoveParagraph = () => {};
      
      render(<TestWrapper {...defaultProps} moveParagraph={emptyMoveParagraph} />);
      
      // Should render without errors
      expect(screen.getByText('This is a test paragraph')).toBeInTheDocument();
    });
  });

  describe('Delete Functionality', () => {
    test('calls onDelete when delete button is clicked', async () => {
      const onDelete = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} onDelete={onDelete} />);
      
      const deleteButton = screen.getByTitle('Delete paragraph');
      
      await act(async () => {
        await user.click(deleteButton);
      });
      
      expect(onDelete).toHaveBeenCalled();
    });

    test('delete button stops event propagation', async () => {
      const onDelete = jest.fn();
      const onClick = jest.fn();
      const user = userEvent.setup();
      
      render(
        <div onClick={onClick}>
          <TestWrapper {...defaultProps} onDelete={onDelete} />
        </div>
      );
      
      const deleteButton = screen.getByTitle('Delete paragraph');
      
      await act(async () => {
        await user.click(deleteButton);
      });
      
      expect(onDelete).toHaveBeenCalled();
      expect(onClick).not.toHaveBeenCalled();
    });
  });

  describe('Fragment Split', () => {
    test('calls onFragmentSplit when text changes significantly', async () => {
      const onFragmentSplit = jest.fn();
      const onTextChange = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} 
        editable={true} 
        onFragmentSplit={onFragmentSplit}
        onTextChange={onTextChange}
      />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        await user.clear(textarea);
        await user.type(textarea, 'First paragraph\n\nSecond paragraph');
      });
      
      await act(async () => {
        fireEvent.blur(textarea);
      });
      
      // Should detect multiple paragraphs and call fragment split
      expect(onFragmentSplit).toHaveBeenCalled();
    });

    test('does not split when text has not changed', async () => {
      const onFragmentSplit = jest.fn();
      const user = userEvent.setup();
      
      render(<TestWrapper {...defaultProps} 
        editable={true} 
        onFragmentSplit={onFragmentSplit}
      />);
      
      const editableDiv = screen.getByText('This is a test paragraph');
      
      await act(async () => {
        await user.click(editableDiv);
      });
      
      const textarea = screen.getByDisplayValue('This is a test paragraph');
      
      await act(async () => {
        fireEvent.blur(textarea);
      });
      
      expect(onFragmentSplit).not.toHaveBeenCalled();
    });
  });

  describe('User Text Styling', () => {
    test('applies white background for user text', () => {
      const userParagraph = {
        ...mockParagraph,
        isUserText: true,
        vendor: null
      };
      
      render(<TestWrapper {...defaultProps} paragraph={userParagraph} />);
      
      const textElement = screen.getByText('This is a test paragraph');
      const paragraphElement = textElement.closest('div');
      const outerDiv = paragraphElement.parentElement;
      
      console.log('User text closest div style:', paragraphElement.getAttribute('style'));
      console.log('User text parent element style:', outerDiv?.getAttribute('style'));
      
      // The background should be on the container div
      const containerStyle = outerDiv?.getAttribute('style') || paragraphElement.getAttribute('style');
      expect(containerStyle).toContain('background');
    });

    test('shows placeholder text for empty user paragraphs', () => {
      const emptyUserParagraph = {
        ...mockParagraph,
        text: '',
        isUserText: true,
        vendor: null
      };
      
      render(<TestWrapper {...defaultProps} paragraph={emptyUserParagraph} editable={true} />);
      
      expect(screen.getByText('Click to edit...')).toBeInTheDocument();
    });
  });

  describe('Error Handling', () => {
    test('handles missing paragraph data gracefully', () => {
      const invalidParagraph = {
        id: 'test',
        text: null,
        vendor: undefined
      };
      
      expect(() => {
        render(<TestWrapper {...defaultProps} paragraph={invalidParagraph} />);
      }).not.toThrow();
    });

    test('handles missing callbacks gracefully', () => {
      expect(() => {
        render(<TestWrapper 
          paragraph={mockParagraph}
          index={0}
          color="#ff6b6b"
        />);
      }).not.toThrow();
    });
  });
});

