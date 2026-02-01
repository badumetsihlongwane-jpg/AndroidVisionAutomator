#!/bin/bash
# Setup script for AndroidVisionAutomator

set -e

echo "🚀 AndroidVisionAutomator Setup"
echo "================================"

# Check prerequisites
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi

if ! command -v java &> /dev/null; then
    echo "❌ Java not found (required for Gradle)"
    exit 1
fi

# Setup Python environment
echo "📦 Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "📥 Installing Python dependencies..."
pip install -r requirements.txt

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not set"
    echo "   Run: export ANTHROPIC_API_KEY=sk-..."
else
    echo "✅ ANTHROPIC_API_KEY configured"
fi

# Build Android app (optional)
read -p "Build Android app? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔨 Building Android app..."
    cd android-app
    ./gradlew build
    cd ..
    echo "✅ Android app built"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Export API key: export ANTHROPIC_API_KEY=sk-..."
echo "  2. Start backend: python backend/app.py"
echo "  3. Install Android app: cd android-app && ./gradlew installDebug"
echo "  4. Enable Accessibility Service on your phone"
echo ""
echo "📖 Read docs/ARCHITECTURE.md for more details"
