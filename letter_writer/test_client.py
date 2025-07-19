from letter_writer.client import get_client, ModelVendor, ModelSize
import os
import pytest
from dotenv import load_dotenv

load_dotenv()

# Test data
SYSTEM_PROMPT = "You are a helpful assistant. Keep responses brief and to the point."
USER_MESSAGE = "Hello, how are you today?"

def test_openai_client_tiny_no_search():
    """Test OpenAI client with tiny model without search"""
    client = get_client(ModelVendor.OPENAI)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"OpenAI tiny no search response: {response[:100]}...")

def test_openai_client_tiny_with_search():
    """Test OpenAI client with tiny model with search"""
    client = get_client(ModelVendor.OPENAI)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"OpenAI tiny with search response: {response[:100]}...")

def test_anthropic_client_tiny_no_search():
    """Test Anthropic client with tiny model without search"""
    client = get_client(ModelVendor.ANTHROPIC)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"Anthropic tiny no search response: {response[:100]}...")

def test_anthropic_client_tiny_with_search():
    """Test Anthropic client with tiny model with search"""
    client = get_client(ModelVendor.ANTHROPIC)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"Anthropic tiny with search response: {response[:100]}...")

def test_gemini_client_tiny_no_search():
    """Test Gemini client with tiny model without search"""
    client = get_client(ModelVendor.GEMINI)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"Gemini tiny no search response: {response[:100]}...")

def test_gemini_client_tiny_with_search():
    """Test Gemini client with tiny model with search"""
    client = get_client(ModelVendor.GEMINI)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"Gemini tiny with search response: {response[:100]}...")

def test_mistral_client_tiny_no_search():
    """Test Mistral client with tiny model without search"""
    # Skip if MISTRAL_API_KEY is not set
    if not os.getenv("MISTRAL_API_KEY"):
        pytest.skip("MISTRAL_API_KEY not set")
    
    client = get_client(ModelVendor.MISTRAL)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"Mistral tiny no search response: {response[:100]}...")

def test_mistral_client_tiny_with_search():
    """Test Mistral client with tiny model with search"""
    # Skip if MISTRAL_API_KEY is not set
    if not os.getenv("MISTRAL_API_KEY"):
        pytest.skip("MISTRAL_API_KEY not set")
    
    client = get_client(ModelVendor.MISTRAL)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"Mistral tiny with search response: {response[:100]}...")

def test_grok_client_tiny_no_search():
    """Test Grok client with tiny model without search"""
    # Skip if XAI_API_KEY is not set
    if not os.getenv("XAI_API_KEY"):
        pytest.skip("XAI_API_KEY not set")
    
    client = get_client(ModelVendor.GROK)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"Grok tiny no search response: {response[:100]}...")

def test_grok_client_tiny_with_search():
    """Test Grok client with tiny model with search (should warn and proceed without search)"""
    # Skip if XAI_API_KEY is not set
    if not os.getenv("XAI_API_KEY"):
        pytest.skip("XAI_API_KEY not set")
    
    client = get_client(ModelVendor.GROK)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"Grok tiny with search response: {response[:100]}...")

def test_deepseek_client_tiny_no_search():
    """Test DeepSeek client with tiny model without search"""
    client = get_client(ModelVendor.DEEPSEEK)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=[USER_MESSAGE],
        search=False
    )
    assert response is not None
    assert len(response) > 0
    print(f"DeepSeek tiny no search response: {response[:100]}...")

def test_deepseek_client_tiny_with_search():
    
    client = get_client(ModelVendor.DEEPSEEK)
    response = client.call(
        model_size=ModelSize.TINY,
        system=SYSTEM_PROMPT,
        user_messages=["What are the latest news about AI?"],
        search=True
    )
    assert response is not None
    assert len(response) > 0
    print(f"DeepSeek tiny with search response: {response[:100]}...")

def test_client_factory():
    """Test that get_client returns the correct client type for each vendor"""
    openai_client = get_client(ModelVendor.OPENAI)
    assert type(openai_client).__name__ == "OpenAIClient"
    
    anthropic_client = get_client(ModelVendor.ANTHROPIC)
    assert type(anthropic_client).__name__ == "ClaudeClient"
    
    gemini_client = get_client(ModelVendor.GEMINI)
    assert type(gemini_client).__name__ == "GeminiClient"
    
    # Test Mistral only if API key is available
    if os.getenv("MISTRAL_API_KEY"):
        mistral_client = get_client(ModelVendor.MISTRAL)
        assert type(mistral_client).__name__ == "MistralClient"
    
    # Test Grok only if API key is available
    if os.getenv("XAI_API_KEY"):
        grok_client = get_client(ModelVendor.GROK)
        assert type(grok_client).__name__ == "GrokClient"
