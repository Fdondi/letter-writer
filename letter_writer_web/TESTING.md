# Testing Guide for Letter Writer Web

This guide explains how to test the React UI components in the Letter Writer Web application.

## 🧪 Testing Setup

The project uses a modern testing stack:

- **Jest**: Test runner and assertion library
- **React Testing Library**: Component testing utilities
- **React DnD Test Backend**: For testing drag and drop functionality
- **React DnD Test Utils**: Additional drag and drop testing utilities

## 🚀 Running Tests

### Install Dependencies

First, install the testing dependencies:

```bash
npm install
```

### Run All Tests

```bash
npm test
```

### Run Tests in Watch Mode

```bash
npm run test:watch
```

### Run Tests with Coverage Report

```bash
npm run test:coverage
```

### Run Specific Test Files

```bash
# Using npm scripts
npm test -- LetterTabs.test.jsx

# Using the custom test runner
node test-runner.js --file=LetterTabs.test.jsx
```

## 📁 Test Structure

```
src/
├── components/
│   ├── __tests__/
│   │   ├── LetterTabs.test.jsx          # Main component tests
│   │   ├── Paragraph.test.jsx           # Paragraph component tests
│   │   └── DragDrop.integration.test.jsx # Drag & drop integration tests
├── contexts/
│   └── __tests__/
│       └── HoverContext.test.jsx        # Context provider tests
├── utils/
│   └── __tests__/
│       └── testUtils.js                 # Testing utilities
└── setupTests.js                        # Global test setup
```

## 🧩 Test Coverage

The tests cover the following key areas:

### LetterTabs Component (`LetterTabs.test.jsx`)
- ✅ Rendering all vendor columns
- ✅ Final letter column functionality
- ✅ Paragraph management (add, delete, update)
- ✅ Copy functionality
- ✅ Error handling and bounds checking
- ✅ Column management and layout
- ✅ Drop zone functionality

### Paragraph Component (`Paragraph.test.jsx`)
- ✅ Basic rendering with different paragraph types
- ✅ Editable mode functionality
- ✅ Copy mode for text selection
- ✅ Drag and drop behavior
- ✅ Delete functionality
- ✅ Fragment splitting
- ✅ User text styling
- ✅ Error handling

### Drag and Drop Integration (`DragDrop.integration.test.jsx`)
- ✅ Basic drag and drop operations
- ✅ Reordering within final column
- ✅ Drop zone visual feedback
- ✅ Error handling in drag operations
- ✅ Different drag source behaviors
- ✅ Performance with large datasets

### Context Providers (`HoverContext.test.jsx`)
- ✅ Hover state management
- ✅ Provider error handling

## 🛠 Testing Utilities

The `testUtils.js` file provides helpful utilities:

```javascript
import { renderWithProviders, createMockParagraph, simulateDragDrop } from '../utils/__tests__/testUtils';

// Render component with all necessary providers
const { backend } = renderWithProviders(<YourComponent />);

// Create mock data
const mockParagraph = createMockParagraph({ text: 'Custom text' });

// Simulate drag and drop
simulateDragDrop(backend, sourceElement, targetElement);
```

## 🎯 Key Testing Scenarios

### Testing Drag and Drop

```javascript
test('can drag paragraph to final column', () => {
  const { backend } = renderWithProviders(<LetterTabs {...props} />);
  
  const source = screen.getByText('Source paragraph');
  const target = screen.getByText('Drop target');
  
  simulateDragDrop(backend, source, target);
  
  expect(mockSetFinalParagraphs).toHaveBeenCalled();
});
```

### Testing Error Boundaries

```javascript
test('handles invalid data gracefully', () => {
  const invalidData = [null, undefined, { invalid: 'data' }];
  
  expect(() => {
    render(<Component data={invalidData} />);
  }).not.toThrow();
});
```

### Testing User Interactions

```javascript
test('updates text when edited', async () => {
  const user = userEvent.setup();
  render(<EditableComponent />);
  
  await user.click(screen.getByText('Click to edit'));
  await user.type(screen.getByRole('textbox'), 'New text');
  await user.keyboard('{Enter}');
  
  expect(mockOnChange).toHaveBeenCalledWith('New text');
});
```

## 📊 Coverage Goals

The project aims for:
- **70%+ line coverage**
- **70%+ function coverage**
- **70%+ branch coverage**
- **70%+ statement coverage**

## 🐛 Testing Best Practices

1. **Test Behavior, Not Implementation**: Focus on what the user sees and does
2. **Use Real User Interactions**: Prefer `userEvent` over `fireEvent`
3. **Test Error Cases**: Ensure components handle edge cases gracefully
4. **Mock External Dependencies**: Use mocks for APIs, timers, and complex dependencies
5. **Isolate Tests**: Each test should be independent and not rely on others
6. **Descriptive Test Names**: Make it clear what each test is verifying

## 🔧 Common Issues and Solutions

### Drag and Drop Tests Not Working
```javascript
// Make sure to use TestBackend and proper setup
import { TestBackend } from 'react-dnd-test-backend';
import { renderWithProviders } from '../utils/__tests__/testUtils';
```

### Console Warnings in Tests
```javascript
// Mock problematic APIs in setupTests.js
Object.assign(navigator, {
  clipboard: { writeText: jest.fn(() => Promise.resolve()) }
});
```

### Async Operations
```javascript
// Use waitFor for async operations
await waitFor(() => {
  expect(screen.getByText('Expected text')).toBeInTheDocument();
});
```

## 🚀 CI/CD Integration

To run tests in CI environments:

```bash
# Install dependencies
npm ci

# Run tests with coverage
npm run test:coverage

# Check coverage thresholds
npx jest --coverage --passWithNoTests
```

## 📈 Future Testing Enhancements

- **Visual Regression Testing**: Screenshot comparison tests
- **E2E Testing**: Full user journey tests with Playwright/Cypress
- **Performance Testing**: Component rendering performance tests
- **Accessibility Testing**: Screen reader and keyboard navigation tests

---

For questions about testing or to add new test scenarios, refer to the existing test files for examples and patterns.

