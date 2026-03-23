#!/bin/bash

# Detect the operating system
OS="$(uname -s)"

# Activate the virtual environment and run Streamlit
case "$OS" in
    Linux|Darwin) # Linux or macOS
        echo "Detected OS: $OS"
        source venv/bin/activate
        streamlit run streamlit_viewer.py
        ;;
    CYGWIN*|MINGW*|MSYS*) # Windows (Git Bash or similar)
        echo "Detected OS: Windows"
        source venv/Scripts/activate
        streamlit run streamlit_viewer.py
        ;;
    *)
        echo "Unsupported OS: $OS"
        exit 1
        ;;
esac