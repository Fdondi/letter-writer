import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { HoverProvider, HoverContext } from '../HoverContext';

// Test component that uses the context
const TestComponent = () => {
  const { hoverId, setHoverId } = React.useContext(HoverContext);
  
  return (
    <div>
      <div data-testid="hover-id">{hoverId || 'none'}</div>
      <button onClick={() => setHoverId('test-id')}>Set Hover ID</button>
      <button onClick={() => setHoverId(null)}>Clear Hover ID</button>
    </div>
  );
};

describe('HoverContext', () => {
  test('provides default hover state', () => {
    render(
      <HoverProvider>
        <TestComponent />
      </HoverProvider>
    );
    
    expect(screen.getByTestId('hover-id')).toHaveTextContent('none');
  });

  test('updates hover state when setHoverId is called', () => {
    render(
      <HoverProvider>
        <TestComponent />
      </HoverProvider>
    );
    
    const setButton = screen.getByText('Set Hover ID');
    fireEvent.click(setButton);
    
    expect(screen.getByTestId('hover-id')).toHaveTextContent('test-id');
  });

  test('clears hover state when setHoverId is called with null', () => {
    render(
      <HoverProvider>
        <TestComponent />
      </HoverProvider>
    );
    
    // First set an ID
    const setButton = screen.getByText('Set Hover ID');
    fireEvent.click(setButton);
    expect(screen.getByTestId('hover-id')).toHaveTextContent('test-id');
    
    // Then clear it
    const clearButton = screen.getByText('Clear Hover ID');
    fireEvent.click(clearButton);
    expect(screen.getByTestId('hover-id')).toHaveTextContent('none');
  });

  test('provides default context value when used outside provider', () => {
    render(<TestComponent />);
    
    // Should use the default context values
    expect(screen.getByTestId('hover-id')).toHaveTextContent('none');
    
    // Default setHoverId should be a no-op function
    const setButton = screen.getByText('Set Hover ID');
    fireEvent.click(setButton);
    
    // Should still show 'none' since default setHoverId doesn't do anything
    expect(screen.getByTestId('hover-id')).toHaveTextContent('none');
  });
});
