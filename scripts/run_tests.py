#!/usr/bin/env python3
"""
Test runner script for the Vital Chatwoot Bridge.
Starts all required services and runs integration tests.
"""

import asyncio
import subprocess
import sys
import time
import signal
import os
import atexit
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vital_chatwoot_bridge.utils.logging_config import get_logger
logger = get_logger(__name__)

from vital_chatwoot_bridge.testing.integration_tests import (
    run_single_scenario, run_test_suite, run_all_tests,
    list_available_scenarios, list_available_suites
)


class ServiceManager:
    """Manages starting and stopping test services."""
    
    def __init__(self):
        self.processes = {}
        self.project_root = Path(__file__).parent.parent
        self.pid_file = self.project_root / "test_services.pids"
        self._check_existing_pid_file()
        
        # Register cleanup function to run on exit
        atexit.register(self._cleanup_on_exit)
    
    async def start_service(self, name: str, command: list, cwd: str = None, wait_time: int = 3, show_output: bool = False):
        """Start a service process."""
        logger.info(f"🚀 TEST_RUNNER: Starting {name}...")
        logger.info(f"   TEST_RUNNER: Command: {' '.join(command)}")
        logger.info(f"   TEST_RUNNER: Working directory: {cwd or self.project_root}")
        
        try:
            # For services that need console output (like bridge with logging), don't redirect stdout/stderr
            if show_output:
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.project_root,
                    preexec_fn=os.setsid  # Create new process group
                )
            else:
                process = subprocess.Popen(
                    command,
                    cwd=cwd or self.project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid  # Create new process group
                )
            
            self.processes[name] = process
            logger.info(f"   TEST_RUNNER: Process started with PID: {process.pid}")
            
            # Wait for service to start
            logger.info(f"   TEST_RUNNER: Waiting {wait_time} seconds for startup...")
            await asyncio.sleep(wait_time)
            
            # Check if process is still running
            if process.poll() is None:
                logger.info(f"✅ TEST_RUNNER: {name} started successfully (PID: {process.pid})")
                return True
            else:
                logger.error(f"❌ TEST_RUNNER: {name} failed to start (exit code: {process.returncode})")
                if not show_output:
                    # Only try to get stdout/stderr if we captured them
                    stdout, stderr = process.communicate()
                    logger.error(f"   TEST_RUNNER: stdout: {stdout.decode().strip()}")
                    logger.error(f"   TEST_RUNNER: stderr: {stderr.decode().strip()}")
                else:
                    logger.error(f"   TEST_RUNNER: Check console output above for error details")
                return False
                
        except Exception as e:
            logger.error(f"❌ TEST_RUNNER: Failed to start {name}: {e}")
            return False
    
    def _check_existing_pid_file(self):
        """Check if PID file exists and exit if another instance is running."""
        if self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    content = f.read().strip()
                    # Extract PID (ignore comment lines)
                    for line in content.split('\n'):
                        if not line.startswith('#') and line.strip():
                            existing_pid = int(line.strip())
                            
                            # Check if process is still running
                            try:
                                os.kill(existing_pid, 0)  # Signal 0 just checks if process exists
                                logger.error(f"❌ TEST_RUNNER: Another test runner is already running (PID: {existing_pid})")
                                logger.info(f"   TEST_RUNNER: To kill it: kill -9 {existing_pid}")
                                logger.info(f"   TEST_RUNNER: Or use: ./kill_services.sh")
                                sys.exit(1)
                            except OSError:
                                # Process doesn't exist, remove stale PID file
                                logger.warning(f"⚠️  TEST_RUNNER: Found stale PID file, cleaning up...")
                                self.pid_file.unlink()
                                break
            except (ValueError, IOError) as e:
                logger.warning(f"⚠️  TEST_RUNNER: Invalid PID file, removing: {e}")
                self.pid_file.unlink()
    
    def write_main_pid_file(self):
        """Write main script PID to file for easy killing (kills all child processes)."""
        try:
            main_pid = os.getpid()
            with open(self.pid_file, 'w') as f:
                f.write("# Test Runner Main Process PID\n")
                f.write("# Kill all services: kill -9 $(cat test_services.pids | grep -v '#')\n")
                f.write("# This will kill the main process and all child services\n")
                f.write(f"{main_pid}\n")
            logger.info(f"📋 TEST_RUNNER: Main PID {main_pid} written to {self.pid_file}")
            logger.info(f"    TEST_RUNNER: To kill all services: kill -9 $(cat test_services.pids | grep -v '#')")
        except Exception as e:
            logger.warning(f"⚠️  TEST_RUNNER: Failed to write PID file: {e}")
    
    def _cleanup_pid_file(self):
        """Remove PID file when all services stopped."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                logger.info(f"🗑️  TEST_RUNNER: Removed PID file: {self.pid_file}")
        except Exception as e:
            logger.warning(f"⚠️  TEST_RUNNER: Failed to remove PID file: {e}")
    
    def _cleanup_on_exit(self):
        """Cleanup function called on script exit."""
        try:
            # Stop all services if they're still running
            if self.processes:
                logger.info("\n🛡️  TEST_RUNNER: Cleaning up on exit...")
                self.stop_all_services()
            else:
                # Just clean up PID file if no processes to stop
                self._cleanup_pid_file()
        except Exception as e:
            logger.warning(f"⚠️  TEST_RUNNER: Error during exit cleanup: {e}")
    
    def stop_all_services(self):
        """Stop all running services in proper order."""
        logger.info("\n🛑 TEST_RUNNER: Stopping all services...")
        
        # Define shutdown order: Bridge first to stop WebSocket reconnection attempts
        shutdown_order = [
            "Bridge Service",
            "Mock Chatwoot", 
            "Mock AI Agent 1 (Echo)",
            "Mock AI Agent 2 (Delay)",
            "Mock AI Agent 3 (Error)"
        ]
        
        # Stop services in the defined order
        for service_name in shutdown_order:
            if service_name in self.processes:
                process = self.processes[service_name]
                try:
                    if process.poll() is None:  # Process is still running
                        logger.info(f"   TEST_RUNNER: Stopping {service_name}...")
                        
                        # Send SIGTERM to the process group
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        
                        # Wait for graceful shutdown with longer timeout for bridge
                        timeout = 8 if "Bridge" in service_name else 5
                        try:
                            process.wait(timeout=timeout)
                            logger.info(f"   ✅ TEST_RUNNER: {service_name} stopped gracefully")
                        except subprocess.TimeoutExpired:
                            # Force kill if graceful shutdown fails
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            process.wait()
                            logger.warning(f"   ⚠️  TEST_RUNNER: {service_name} force killed")
                            
                except Exception as e:
                    logger.error(f"   ❌ TEST_RUNNER: Error stopping {service_name}: {e}")
        
        # Stop any remaining services not in the shutdown order
        for name, process in self.processes.items():
            if name not in shutdown_order:
                try:
                    if process.poll() is None:
                        logger.info(f"   TEST_RUNNER: Stopping remaining service {name}...")
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                            logger.info(f"   ✅ TEST_RUNNER: {name} stopped gracefully")
                        except subprocess.TimeoutExpired:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            process.wait()
                            logger.warning(f"   ⚠️  TEST_RUNNER: {name} force killed")
                except Exception as e:
                    logger.error(f"   ❌ TEST_RUNNER: Error stopping {name}: {e}")
        
        self.processes.clear()
        self._cleanup_pid_file()
    
    def _parse_required_agents(self):
        """Parse configuration to determine which unique agents need to be spawned."""
        import json
        import os
        from urllib.parse import urlparse
        from pathlib import Path
        
        # Load .env file to get configuration (test runner doesn't auto-load it)
        env_file = Path(self.project_root) / '.env'
        if env_file.exists():
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        os.environ[key] = value
        
        # Get configuration from environment
        mappings_json = os.getenv('INBOX_AGENT_MAPPINGS', '[]')
        logger.info(f"🔍 TEST_RUNNER: Raw INBOX_AGENT_MAPPINGS env var: {mappings_json[:200]}..." if len(mappings_json) > 200 else f"🔍 TEST_RUNNER: Raw INBOX_AGENT_MAPPINGS env var: {mappings_json}")
        
        try:
            mappings_data = json.loads(mappings_json)
            logger.info(f"🔍 TEST_RUNNER: Parsed {len(mappings_data)} mappings from JSON")
            unique_agents = {}
            
            for mapping in mappings_data:
                agent_config = mapping.get('agent_config', {})
                websocket_url = agent_config.get('websocket_url', '')
                agent_id = agent_config.get('agent_id', '')
                
                if websocket_url and agent_id:
                    # Parse URL to get host and port
                    parsed = urlparse(websocket_url)
                    host = parsed.hostname or 'localhost'
                    port = parsed.port
                    
                    if port:
                        # Determine behavior based on agent_id or port (fallback logic)
                        behavior = 'echo'  # default
                        if 'delay' in agent_id.lower() or port == 8086:
                            behavior = 'delay'
                        elif 'error' in agent_id.lower() or port == 8087:
                            behavior = 'error'
                        
                        # Use websocket_url as key to ensure uniqueness
                        unique_agents[websocket_url] = {
                            'agent_id': agent_id,
                            'host': host,
                            'port': port,
                            'behavior': behavior
                        }
            
            logger.info(f"📋 TEST_RUNNER: Found {len(unique_agents)} unique agents to spawn")
            for url, config in unique_agents.items():
                logger.info(f"   TEST_RUNNER: {config['agent_id']} -> {url} ({config['behavior']})")
            
            return list(unique_agents.values())
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"❌ TEST_RUNNER: Failed to parse agent configuration: {e}")
            # Fallback to default agents for testing
            return [
                {'agent_id': 'agent_1', 'host': 'localhost', 'port': 8085, 'behavior': 'echo'},
                {'agent_id': 'agent_2', 'host': 'localhost', 'port': 8086, 'behavior': 'delay'},
                {'agent_id': 'agent_3', 'host': 'localhost', 'port': 8087, 'behavior': 'error'}
            ]
    
    async def start_all_services(self):
        """Start all required services for testing."""
        # Get unique agents from configuration
        required_agents = self._parse_required_agents()
        
        # Build services list dynamically
        services = []
        
        # Add mock agents
        for agent in required_agents:
            services.append({
                "name": f"Mock AI Agent {agent['agent_id']} ({agent['behavior'].title()})",
                "command": [
                    sys.executable, "-m", "vital_chatwoot_bridge.agents.mock_agent",
                    agent['host'], str(agent['port']), agent['behavior']
                ],
                "wait_time": 4,
                "show_output": True
            })
        
        # Add other services
        services.extend([
            {
                "name": "Mock Chatwoot",
                "command": [
                    sys.executable, "-m", "vital_chatwoot_bridge.testing.mock_chatwoot",
                    "localhost", "9000"
                ],
                "wait_time": 3
            },
            {
                "name": "Bridge Service",
                "command": [
                    sys.executable, "-m", "uvicorn",
                    "vital_chatwoot_bridge.main:app",
                    "--host", "localhost",
                    "--port", "8000",
                    "--reload"
                ],
                "wait_time": 6,  # Increased wait time for WebSocket connections to establish
                "show_output": True
            }
        ])
        
        success_count = 0
        for service in services:
            success = await self.start_service(**service)
            if success:
                success_count += 1
        
        if success_count == len(services):
            logger.info(f"\n✅ TEST_RUNNER: All {len(services)} services started successfully!")
            
            # Write main PID to file for easy killing
            self.write_main_pid_file()
            
            logger.info("🔗 TEST_RUNNER: Service URLs:")
            logger.info("   TEST_RUNNER: Bridge:           http://localhost:8000")
            logger.info("   TEST_RUNNER: Mock Chatwoot:    http://localhost:9000")
            
            # Display dynamically spawned agents
            for agent in required_agents:
                logger.info(f"   TEST_RUNNER: Mock AI Agent {agent['agent_id']}:  ws://{agent['host']}:{agent['port']} ({agent['behavior']})")
            return True
        else:
            logger.error(f"\n❌ TEST_RUNNER: Only {success_count}/{len(services)} services started")
            return False


async def main():
    """Main test runner function."""
    if len(sys.argv) < 2:
        logger.info("TEST_RUNNER: Vital Chatwoot Bridge Test Runner")
        logger.info("TEST_RUNNER: " + "=" * 40)
        logger.info("TEST_RUNNER: Usage:")
        logger.info("TEST_RUNNER:   python run_tests.py start-services    # Start all services")
        logger.info("TEST_RUNNER:   python run_tests.py scenario <name>   # Run single scenario")
        logger.info("TEST_RUNNER:   python run_tests.py suite <name>      # Run test suite")
        logger.info("TEST_RUNNER:   python run_tests.py all               # Run all tests")
        logger.info("TEST_RUNNER:   python run_tests.py list              # List available tests")
        logger.info("TEST_RUNNER:   python run_tests.py full-test         # Start services + run all tests")
        logger.info("TEST_RUNNER: \nAvailable scenarios:")
        for scenario in list_available_scenarios():
            logger.info(f"TEST_RUNNER:   - {scenario}")
        logger.info("TEST_RUNNER: \nAvailable suites:")
        for suite in list_available_suites():
            logger.info(f"TEST_RUNNER:   - {suite}")
        return
    
    command = sys.argv[1]
    service_manager = ServiceManager()
    
    # Setup signal handler for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"\n🛑 TEST_RUNNER: Received signal {signum}, shutting down...")
        service_manager.stop_all_services()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if command == "start-services":
            success = await service_manager.start_all_services()
            if success:
                logger.info("\n⏳ TEST_RUNNER: Services are running. Press Ctrl+C to stop.")
                # Keep services running until interrupted
                try:
                    while True:
                        await asyncio.sleep(1)
                except KeyboardInterrupt:
                    pass
            
        elif command == "list":
            logger.info("TEST_RUNNER: Available scenarios:")
            for scenario in list_available_scenarios():
                logger.info(f"TEST_RUNNER:   - {scenario}")
            logger.info("TEST_RUNNER: \nAvailable suites:")
            for suite in list_available_suites():
                logger.info(f"TEST_RUNNER:   - {suite}")
        
        elif command == "scenario":
            if len(sys.argv) < 3:
                logger.error("❌ TEST_RUNNER: Please specify scenario name")
                return
            
            scenario_name = sys.argv[2]
            logger.info(f"🧪 TEST_RUNNER: Running scenario: {scenario_name}")
            
            result = await run_single_scenario(scenario_name)
            if result:
                if result.success:
                    logger.info(f"\n✅ TEST_RUNNER: Scenario '{scenario_name}' PASSED")
                else:
                    logger.error(f"\n❌ TEST_RUNNER: Scenario '{scenario_name}' FAILED")
                    for error in result.errors:
                        logger.error(f"   TEST_RUNNER: Error: {error}")
            
        elif command == "suite":
            if len(sys.argv) < 3:
                logger.error("❌ TEST_RUNNER: Please specify suite name")
                return
            
            suite_name = sys.argv[2]
            logger.info(f"🎯 TEST_RUNNER: Running test suite: {suite_name}")
            
            results = await run_test_suite(suite_name)
            if results:
                passed = sum(1 for r in results if r.success)
                total = len(results)
                
                if passed == total:
                    logger.info(f"\n✅ TEST_RUNNER: Test suite '{suite_name}' PASSED ({passed}/{total})")
                else:
                    logger.error(f"\n❌ TEST_RUNNER: Test suite '{suite_name}' FAILED ({passed}/{total})")
        
        elif command == "all":
            logger.info("🎯 TEST_RUNNER: Running all test suites...")
            
            all_results = await run_all_tests()
            if all_results:
                total_passed = 0
                total_tests = 0
                
                for suite_name, results in all_results.items():
                    passed = sum(1 for r in results if r.success)
                    total = len(results)
                    total_passed += passed
                    total_tests += total
                    
                    status = "✅" if passed == total else "❌"
                    logger.info(f"TEST_RUNNER: {status} {suite_name}: {passed}/{total}")
                
                if total_passed == total_tests:
                    logger.info(f"\n🎉 TEST_RUNNER: ALL TESTS PASSED ({total_passed}/{total_tests})")
                else:
                    logger.error(f"\n❌ TEST_RUNNER: SOME TESTS FAILED ({total_passed}/{total_tests})")
        
        elif command == "full-test":
            logger.info("🚀 TEST_RUNNER: Starting full test cycle...")
            logger.info("   TEST_RUNNER: 1. Starting all services")
            logger.info("   TEST_RUNNER: 2. Running all tests")
            logger.info("   TEST_RUNNER: 3. Stopping services")
            
            # Start services
            success = await service_manager.start_all_services()
            if not success:
                logger.error("❌ TEST_RUNNER: Failed to start services")
                return
            
            # Wait longer for services to fully initialize and establish WebSocket connections
            logger.info("\n⏳ TEST_RUNNER: Waiting for services to initialize...")
            await asyncio.sleep(10)
            
            # Additional health check - verify bridge service is responding
            logger.info("🔍 TEST_RUNNER: Checking service health...")
            import httpx
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get("http://localhost:8000/health", timeout=5)
                    if response.status_code == 200:
                        logger.info("✅ TEST_RUNNER: Bridge service is healthy")
                    else:
                        logger.warning(f"⚠️ TEST_RUNNER: Bridge service health check returned {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ TEST_RUNNER: Bridge service health check failed: {e}")
            
            # Give WebSocket connections more time to establish
            logger.info("🔌 TEST_RUNNER: Allowing time for WebSocket connections...")
            await asyncio.sleep(5)
            
            # Verify WebSocket connections are established
            logger.info("🔍 TEST_RUNNER: Verifying WebSocket connections...")
            websocket_ready = False
            for attempt in range(10):  # Try for up to 10 seconds
                try:
                    async with httpx.AsyncClient() as client:
                        # Check bridge service logs or status for WebSocket connection status
                        # For now, we'll just wait a bit more and assume success if bridge is healthy
                        response = await client.get("http://localhost:8000/health", timeout=2)
                        if response.status_code == 200:
                            websocket_ready = True
                            logger.info("✅ TEST_RUNNER: WebSocket connections appear ready")
                            break
                except Exception as e:
                    logger.debug(f"WebSocket readiness check attempt {attempt + 1}: {e}")
                
                await asyncio.sleep(1)
            
            if not websocket_ready:
                logger.warning("⚠️ TEST_RUNNER: Could not verify WebSocket readiness, proceeding anyway...")
            
            # Run all tests
            logger.info("\n🧪 TEST_RUNNER: Running all tests...")
            all_results = await run_all_tests()
            
            # Print summary
            if all_results:
                total_passed = 0
                total_tests = 0
                
                logger.info("\n📊 TEST_RUNNER: Test Results Summary:")
                logger.info("TEST_RUNNER: " + "=" * 40)
                
                for suite_name, results in all_results.items():
                    passed = sum(1 for r in results if r.success)
                    total = len(results)
                    total_passed += passed
                    total_tests += total
                    
                    status = "✅" if passed == total else "❌"
                    logger.info(f"TEST_RUNNER: {status} {suite_name}: {passed}/{total}")
                
                logger.info("TEST_RUNNER: " + "=" * 40)
                if total_passed == total_tests:
                    logger.info(f"🎉 TEST_RUNNER: ALL TESTS PASSED ({total_passed}/{total_tests})")
                else:
                    logger.error(f"❌ TEST_RUNNER: SOME TESTS FAILED ({total_passed}/{total_tests})")
            
        else:
            logger.error(f"❌ TEST_RUNNER: Unknown command: {command}")
    
    finally:
        service_manager.stop_all_services()


if __name__ == "__main__":
    asyncio.run(main())
