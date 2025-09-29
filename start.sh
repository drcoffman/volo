#!/bin/bash
# Navigate to the project directory

# Activate virtual environment
source venv/bin/activate

# Start the Flask server in the background
echo "Starting..."
python3 flaskserver.py &

# Install npm packages and start React server
npm install react axios react-markdown remark-math rehype-katex --force
npm run start-server