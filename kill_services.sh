#!/bin/bash
# Kill script for test services
# This will gracefully stop the main test runner process and all child services

PID_FILE="test_services.pids"

echo "🛑 Stopping test services..."

# Check if PID file exists
if [ ! -f "$PID_FILE" ]; then
    echo "   ⚠️  PID file '$PID_FILE' not found. Services may not be running."
    echo "   ✅ Nothing to clean up."
    exit 0
fi

# Read the main PID from the file (ignore comment lines)
MAIN_PID=$(cat "$PID_FILE" | grep -v '#' | head -1)

if [ -z "$MAIN_PID" ]; then
    echo "   ❌ No PID found in $PID_FILE"
    echo "   🗑️  Removing invalid PID file..."
    rm -f "$PID_FILE"
    exit 0
fi

echo "   Main process PID: $MAIN_PID"

# Check if process is running
if ! kill -0 "$MAIN_PID" 2>/dev/null; then
    echo "   ⚠️  Process $MAIN_PID is not running (leftover PID file)"
    rm -f "$PID_FILE"
    echo "   🗑️  Cleaned up leftover PID file"
    exit 0
fi

# Send SIGINT (Control-C equivalent) for graceful shutdown
echo "   Sending SIGINT (Ctrl-C) for graceful shutdown..."
kill -INT "$MAIN_PID" 2>/dev/null

# Wait for graceful shutdown
echo "   Waiting 5 seconds for graceful shutdown..."
sleep 5

# Check if still running
if kill -0 "$MAIN_PID" 2>/dev/null; then
    echo "   Process still running, sending SIGTERM..."
    kill -TERM "$MAIN_PID" 2>/dev/null
    sleep 3
    
    # Final check and force kill if necessary
    if kill -0 "$MAIN_PID" 2>/dev/null; then
        echo "   Process still running, sending SIGKILL (force kill)..."
        kill -KILL "$MAIN_PID" 2>/dev/null
        sleep 1
    fi
fi

# Verify process is dead and clean up
if ! kill -0 "$MAIN_PID" 2>/dev/null; then
    echo "   ✅ All services stopped successfully"
    rm -f "$PID_FILE"
    echo "   🗑️  Cleaned up PID file"
else
    echo "   ❌ Failed to kill process $MAIN_PID"
    echo "   You may need to manually kill it: kill -9 $MAIN_PID"
    exit 1
fi
