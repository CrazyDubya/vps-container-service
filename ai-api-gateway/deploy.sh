#!/bin/bash
# SiloedBoss API Management Deployment Script

set -e  # Exit on any error

echo "🚀 Starting SiloedBoss API Management deployment..."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env file with your API keys before running the application."
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Run basic tests
echo "🧪 Running tests..."
python test_basic.py

# Check if application starts
echo "🔍 Testing application startup..."
timeout 10s uvicorn main:app --host 127.0.0.1 --port 8001 &
SERVER_PID=$!
sleep 5

# Test health endpoint
if curl -f http://127.0.0.1:8001/health > /dev/null 2>&1; then
    echo "✅ Health check passed!"
else
    echo "❌ Health check failed!"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

# Stop test server
kill $SERVER_PID 2>/dev/null || true

echo "✅ Deployment checks complete!"
echo ""
echo "To start the application:"
echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo "To build Docker container:"
echo "  docker build -t siloed-boss-api ."
echo "  docker run -p 8000:8000 --env-file .env siloed-boss-api"