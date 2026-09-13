# SiloedBoss API Management System

An advanced multi-provider API management system that orchestrates conversations between local and cloud-based AI models. SiloedBoss enables sophisticated task delegation, rate limiting, and intelligent workflow management across multiple AI providers.

## 🎯 Features

- **Multi-Provider API Integration**: Seamless integration with OpenAI, Claude, Gemini, Perplexity, and local models
- **Intelligent Task Delegation**: Automatic routing between Mixtral (conversation orchestrator) and WizardCoder-17b (technical specialist)
- **Advanced Rate Limiting**: Sophisticated request and token-based rate limiting with automatic backoff
- **Memory Management**: Dual-layer memory system with long-term and short-term conversation context
- **XML Task Persistence**: Structured task storage and retrieval using XML format
- **Real-time Processing**: FastAPI-powered web interface with real-time task processing
- **Structured Response Parsing**: Intelligent extraction of responses, questions, and tasks from AI outputs

## 🏗️ Architecture

### Core Components

- **Mixtral Orchestrator**: Primary conversation manager that delegates tasks and coordinates responses
- **WizardCoder-17b**: Technical specialist for coding and detailed technical queries
- **Multi-API Router**: Intelligent routing system for different AI providers
- **Rate Limiter**: Advanced rate limiting with request and token-based controls
- **Memory System**: Context-aware memory management for conversation continuity
- **Task Manager**: XML-based task persistence and retrieval system

### API Providers Supported

- **OpenAI**: GPT models with cost optimization
- **Claude (Anthropic)**: Haiku, Sonnet, and Opus models
- **Gemini**: Google's AI models including vision capabilities
- **Perplexity**: Code-specialized models (CodeLlama, Mistral, Mixtral)
- **Monster API**: Falcon and MPT model variants
- **Local Models**: Self-hosted Mixtral and WizardCoder instances

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- API keys for desired providers (OpenAI, Claude, Gemini, Perplexity)
- Local model servers (optional)

### Installation

1. **Clone and setup**:
   ```bash
   git clone https://github.com/CrazyDubya/siloed-boss-api-management.git
   cd siloed-boss-api-management
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Add your API keys to .env
   ```

4. **Run the system**:
   ```bash
   uvicorn main:app --reload
   ```

5. **Access the interface**:
   Open `http://localhost:8000` in your browser

## ⚙️ Configuration

### Environment Variables

```bash
# Required: API Keys for cloud providers
OPENAI_API_KEY=your_openai_key_here
CLAUDE_API_KEY=your_claude_key_here
GEMINI_API_KEY=your_gemini_key_here
PERPLEXITY_API_KEY=your_perplexity_key_here
MONSTER_API_KEY=your_monster_api_key_here

# Optional: Local model configuration
LOCAL_MIXTRAL_PORT=8080
LOCAL_WIZARD_PORT=8081
LOCAL_MODEL_HOST=localhost

# System settings
MAX_ITERATIONS=4000
MAX_REQUESTS_PER_MINUTE=15
MAX_TOKENS_PER_MINUTE=450000
```

### Model Configuration

The system uses a cost-based model selection strategy defined in `apis/config.json`:

```json
{
  "CLAUDE_MODELS": {
    "haiku": {"name": "claude-3-haiku-20240307", "cost": "$"},
    "sonnet": {"name": "claude-3-sonnet-20240229", "cost": "$$"},
    "opus": {"name": "claude-3-opus-20240229", "cost": "$$$$"}
  },
  "OPENAI_MODELS": {
    "gpt-3.5-turbo-0125": {"cost": "$$$"}
  }
}
```

## 🔧 API Usage

### Process Task Endpoint

```python
POST /process
{
    "user_input": "Build a web scraper for product data",
    "task_id": 12345
}
```

**Response Format**:
```json
{
    "response_to_user": "I'll help you build a web scraper...",
    "questions_for_user": ["What specific websites?", "What data fields?"],
    "tasks": ["Research scraping libraries", "Design data schema"]
}
```

### Task History

```python
GET /task-history
```

Returns a list of completed tasks with their IDs and status.

## 🧠 Intelligent Features

### Multi-Agent Conversation Flow

1. **User Input Processing**: Initial input is processed by Mixtral orchestrator
2. **Task Analysis**: System determines if technical expertise is needed
3. **Delegation**: Complex technical tasks are routed to WizardCoder-17b
4. **Response Integration**: Responses from specialists are integrated into final output
5. **Context Management**: Long and short-term memory maintain conversation context

### Structured Response System

The system uses XML-like tags for structured communication:

- `<Response_to_User>`: Direct user-facing responses
- `<questions_for_user>`: Follow-up questions for clarification
- `<tasks>`: Action items and next steps
- `<wizard_task>`: Technical tasks for specialist AI
- `<internal_monologue>`: AI reasoning and context

### Rate Limiting & Optimization

- **Request-based limiting**: Maximum requests per minute per provider
- **Token-based limiting**: Intelligent token usage tracking
- **Automatic backoff**: Dynamic delay insertion during high usage
- **Cost optimization**: Automatic model selection based on task complexity

## 📊 Task Management

### XML Task Storage

Tasks are automatically stored in XML format for persistence:

```xml
<task id="12345">
    <user_input>Build a web scraper</user_input>
    <mixtral_response>...</mixtral_response>
    <wizard_response>...</wizard_response>
    <completion_status>processed</completion_status>
</task>
```

### Memory System

- **Long Memory**: Persistent context across multiple conversations
- **Short Memory**: Recent conversation context (last 5 exchanges)
- **Adaptive Sampling**: Random sampling from memory pools for context injection

## 🔒 Security & Best Practices

- **Environment Variable Management**: All API keys stored securely in environment variables
- **CORS Configuration**: Configurable cross-origin resource sharing
- **Input Validation**: Pydantic models for request validation
- **Error Handling**: Graceful error handling with informative responses
- **Rate Limiting**: Built-in protection against API quota exhaustion

## 🚀 Deployment

### Development

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker Deployment

```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 📈 Performance Optimization

- **Async Processing**: FastAPI async capabilities for concurrent request handling
- **Intelligent Caching**: Response caching for repeated queries
- **Load Balancing**: Automatic distribution across available model providers
- **Resource Monitoring**: Real-time tracking of API usage and costs

## 🛠️ Advanced Features

### Custom Prompt Engineering

The system includes sophisticated prompt refinement:

```python
def analyze_and_refine_prompt(self, internal_monologue, system_prompt):
    refined_prompt = system_prompt + " " + internal_monologue
    # Add memory context sampling
    # Apply conversation continuity
    return refined_prompt
```

### Intelligent Question Generation

Automatic generation of clarifying questions based on AI analysis:

```python
def extract_questions_for_user(self, content):
    # Parse structured AI responses for questions
    questions = self.extract_tag(content, "questions_for_user")
    return questions.split("\n") if questions else []
```

## 📁 Project Structure

```
siloed-boss-api-management/
├── apis/
│   ├── config.json          # Model configuration
│   ├── openai.py           # OpenAI integration
│   ├── claude_3.py         # Claude integration
│   ├── gemini.py           # Gemini integration
│   ├── perplexity.py       # Perplexity integration
│   ├── monster.py          # Monster API integration
│   └── local.py            # Local model integration
├── main.py                 # FastAPI application
├── index.html              # Web interface
├── requirements.txt        # Dependencies
└── task_*.xml             # Stored tasks
```

## 🧪 Testing

### API Testing

```bash
# Test task processing
curl -X POST "http://localhost:8000/process" \
     -H "Content-Type: application/json" \
     -d '{"user_input": "Test query", "task_id": 1}'

# Test task history
curl "http://localhost:8000/task-history"
```

### Load Testing

```bash
# Use included load testing script
python test_load.py --concurrent 10 --requests 100
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow async/await patterns for all API calls
- Add comprehensive logging for debugging
- Include rate limiting in new API integrations
- Test with multiple providers before committing

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- FastAPI for the excellent web framework
- All supported AI providers for their powerful APIs
- The open-source community for continuous inspiration

## 📞 Support

For questions, issues, or contributions:

- Open an issue on GitHub
- Check the API documentation in the code
- Review the example tasks in the test files

---

**Note**: This system is designed for development and research purposes. Always respect API rate limits and terms of service for all providers.