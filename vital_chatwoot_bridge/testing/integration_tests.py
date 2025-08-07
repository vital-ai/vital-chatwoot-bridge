"""
End-to-end integration tests for the Vital Chatwoot Bridge.
"""

import asyncio
import logging
import re
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import httpx
from pydantic import BaseModel

from vital_chatwoot_bridge.testing.test_scenarios import (
    TestScenario, TestSuite, TestMessage,
    get_scenario_by_name, get_suite_by_name,
    list_available_scenarios, list_available_suites
)
from vital_chatwoot_bridge.testing.mock_chatwoot import WebhookTriggerRequest
from vital_chatwoot_bridge.agents.models import MockAgentBehavior

logger = logging.getLogger(__name__)


class TestResult(BaseModel):
    """Test execution result."""
    scenario_name: str
    success: bool
    duration_seconds: float
    messages_sent: int
    responses_received: int
    errors: List[str] = []
    details: Dict[str, Any] = {}


class IntegrationTestRunner:
    """Integration test runner for the bridge system."""
    
    def __init__(
        self,
        bridge_url: str = "http://localhost:8000",
        mock_chatwoot_url: str = "http://localhost:9000",
        mock_agent_url: str = "ws://localhost:8080"
    ):
        self.bridge_url = bridge_url
        self.mock_chatwoot_url = mock_chatwoot_url
        self.mock_agent_url = mock_agent_url
        self.client = httpx.AsyncClient(timeout=60.0)
        
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()
    
    async def wait_for_services(self, timeout_seconds: int = 30) -> bool:
        """Wait for all services to be ready."""
        services = [
            (f"{self.bridge_url}/health", "Bridge"),
            (f"{self.mock_chatwoot_url}/mock/health", "Mock Chatwoot"),
        ]
        
        start_time = time.time()
        
        for url, name in services:
            logger.info(f"🔍 INTEGRATION TEST: Checking {name} service at {url}...")
            attempts = 0
            while time.time() - start_time < timeout_seconds:
                attempts += 1
                try:
                    logger.info(f"   INTEGRATION TEST: Attempt {attempts}: Connecting to {url}")
                    response = await self.client.get(url)
                    logger.info(f"   INTEGRATION TEST: Response: {response.status_code}")
                    if response.status_code == 200:
                        logger.info(f"✅ INTEGRATION TEST: {name} service is ready")
                        break
                    else:
                        logger.warning(f"   Unexpected status code: {response.status_code}")
                except Exception as e:
                    logger.error(f"   Connection failed: {type(e).__name__}: {str(e)}")
                
                elapsed = time.time() - start_time
                remaining = timeout_seconds - elapsed
                logger.info(f"   INTEGRATION TEST: Waiting 1s... ({remaining:.1f}s remaining)")
                await asyncio.sleep(1)
            else:
                logger.error(f"❌ INTEGRATION TEST: {name} service failed to start within {timeout_seconds}s")
                return False
        
        return True
    
    async def setup_test_environment(self) -> bool:
        """Setup the test environment."""
        try:
            # Register bridge webhook with mock Chatwoot
            webhook_registration = {
                "url": f"{self.bridge_url}/webhook/chatwoot",
                "events": ["message_created", "conversation_created", "webwidget_triggered"]
            }
            
            response = await self.client.post(
                f"{self.mock_chatwoot_url}/mock/webhook/register",
                json=webhook_registration
            )
            
            if response.status_code != 200:
                logger.error(f"❌ TEST: Failed to register webhook: {response.text}")
                return False
            
            # Reset mock data
            await self.client.delete(f"{self.mock_chatwoot_url}/mock/api/reset")
            
            logger.info("✅ TEST: Test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"❌ TEST: Failed to setup test environment: {e}")
            return False
    
    async def run_scenario(self, scenario: TestScenario) -> TestResult:
        """Run a single test scenario."""
        logger.info(f"\n🧪 TEST: Running scenario: {scenario.name}")
        logger.info(f"   TEST: Description: {scenario.description}")
        
        start_time = time.time()
        result = TestResult(
            scenario_name=scenario.name,
            success=False,
            duration_seconds=0,
            messages_sent=0,
            responses_received=0
        )
        
        try:
            # Setup agent behavior if needed
            if hasattr(scenario, 'agent_behavior'):
                await self._configure_mock_agent(scenario.agent_behavior)
            
            # Send messages and collect responses
            for i, message in enumerate(scenario.messages):
                if message.delay_before_send > 0:
                    await asyncio.sleep(message.delay_before_send)
                
                await self._send_test_message(scenario.inbox_id, message.content)
                result.messages_sent += 1
                
                logger.info(f"📨 INTEGRATION TEST: Sending test message: {message.content[:50]}...")
            
            # Wait for responses
            responses = await self._wait_for_responses(
                scenario.expected_responses,
                scenario.timeout_seconds
            )
            
            result.responses_received = len(responses)
            
            # Validate responses
            validation_success = await self._validate_responses(
                scenario.messages,
                responses,
                result
            )
            
            result.success = (
                result.messages_sent == len(scenario.messages) and
                result.responses_received >= scenario.expected_responses and
                validation_success
            )
            
            result.details = {
                "responses": responses,
                "expected_responses": scenario.expected_responses,
                "validation_success": validation_success
            }
            
        except Exception as e:
            result.errors.append(f"Scenario execution error: {str(e)}")
            logger.error(f"   TEST: Error: {e}")
        
        finally:
            result.duration_seconds = time.time() - start_time
        
        status = "✅ PASSED" if result.success else "❌ FAILED"
        logger.info(f"   TEST: {status} ({result.duration_seconds:.2f}s)")
        
        if result.errors:
            for error in result.errors:
                logger.error(f"      TEST: Error: {error}")
        
        return result
    
    async def run_suite(self, suite: TestSuite) -> List[TestResult]:
        """Run a test suite."""
        logger.info(f"\n🎯 TEST: Running test suite: {suite.name}")
        logger.info(f"   TEST: Description: {suite.description}")
        logger.info(f"   TEST: Scenarios: {len(suite.scenarios)}")
        
        results = []
        
        if suite.parallel_execution:
            # Run scenarios in parallel
            tasks = [self.run_scenario(scenario) for scenario in suite.scenarios]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Convert exceptions to failed results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    results[i] = TestResult(
                        scenario_name=suite.scenarios[i].name,
                        success=False,
                        duration_seconds=0,
                        messages_sent=0,
                        responses_received=0,
                        errors=[f"Execution exception: {str(result)}"]
                    )
        else:
            # Run scenarios sequentially
            for scenario in suite.scenarios:
                result = await self.run_scenario(scenario)
                results.append(result)
                
                if not result.success and suite.stop_on_failure:
                    logger.warning(f"   ⏹️  TEST: Stopping suite due to failure in {scenario.name}")
                    break
        
        # Print suite summary
        passed = sum(1 for r in results if r.success)
        total = len(results)
        logger.info(f"\n📊 TEST: Suite Results: {passed}/{total} passed")
        
        return results
    
    async def _configure_mock_agent(self, behavior: MockAgentBehavior):
        """Configure mock agent behavior."""
        # This would send a configuration message to the mock agent
        # For now, we assume the agent is configured via environment or startup
        pass
    
    async def _send_test_message(self, inbox_id: str, content: str):
        """Send a test message via mock Chatwoot."""
        trigger_request = WebhookTriggerRequest(
            inbox_id=inbox_id,
            content=content,
            sender_name="Test User",
            sender_email="test@example.com"
        )
        
        response = await self.client.post(
            f"{self.mock_chatwoot_url}/mock/webhook/trigger/message_created",
            json=trigger_request.dict()
        )
        
        if response.status_code != 200:
            raise Exception(f"Failed to send test message: {response.text}")
    
    async def _wait_for_responses(self, expected_count: int, timeout_seconds: int) -> List[Dict[str, Any]]:
        """Wait for responses from mock Chatwoot."""
        start_time = time.time()
        responses = []
        max_attempts = min(timeout_seconds * 2, 40)  # Max 40 attempts or 2 per second
        attempt_count = 0
        
        while time.time() - start_time < timeout_seconds and attempt_count < max_attempts:
            attempt_count += 1
            try:
                response = await self.client.get(
                    f"{self.mock_chatwoot_url}/mock/api/received_messages"
                )
                
                if response.status_code == 200:
                    data = response.json()
                    current_responses = data.get("messages", [])
                    
                    # Get new responses since last check
                    new_responses = current_responses[len(responses):]
                    responses.extend(new_responses)
                    
                    if len(responses) >= expected_count:
                        logger.info(f"   TEST: Found {len(responses)} responses after {attempt_count} attempts")
                        break
                
            except Exception as e:
                logger.warning(f"   TEST: Warning: Error checking responses (attempt {attempt_count}): {e}")
            
            # Only sleep if we haven't reached our limits
            if time.time() - start_time < timeout_seconds and attempt_count < max_attempts:
                await asyncio.sleep(0.5)
        
        if attempt_count >= max_attempts:
            logger.warning(f"   TEST: Stopped after {max_attempts} attempts (timeout protection)")
        
        return responses
    
    async def _validate_responses(
        self,
        messages: List[TestMessage],
        responses: List[Dict[str, Any]],
        result: TestResult
    ) -> bool:
        """Validate that responses match expected patterns."""
        if len(responses) < len(messages):
            result.errors.append(f"Expected {len(messages)} responses, got {len(responses)}")
            return False
        
        validation_success = True
        
        for i, (message, response) in enumerate(zip(messages, responses)):
            response_content = response.get("content", "")
            expected_pattern = message.expected_response_pattern
            
            if not re.search(expected_pattern, response_content, re.IGNORECASE):
                result.errors.append(
                    f"Message {i+1} response doesn't match pattern. "
                    f"Expected: {expected_pattern}, Got: {response_content}"
                )
                validation_success = False
            else:
                logger.info(f"   ✅ TEST: Response {i+1} matches expected pattern")
        
        return validation_success


# CLI interface functions
async def run_single_scenario(scenario_name: str) -> TestResult:
    """Run a single test scenario by name."""
    try:
        scenario = get_scenario_by_name(scenario_name)
    except ValueError as e:
        logger.error(f"❌ TEST: {e}")
        logger.info(f"TEST: Available scenarios: {', '.join(list_available_scenarios())}")
        return None
    
    async with IntegrationTestRunner() as runner:
        if not await runner.wait_for_services():
            logger.error("❌ TEST: Services not ready")
            return None
        
        if not await runner.setup_test_environment():
            logger.error("❌ TEST: Failed to setup test environment")
            return None
        
        return await runner.run_scenario(scenario)


async def run_test_suite(suite_name: str) -> List[TestResult]:
    """Run a test suite by name."""
    try:
        suite = get_suite_by_name(suite_name)
    except ValueError as e:
        logger.error(f"❌ TEST: {e}")
        logger.info(f"TEST: Available suites: {', '.join(list_available_suites())}")
        return None
    
    async with IntegrationTestRunner() as runner:
        if not await runner.wait_for_services():
            logger.error("❌ TEST: Services not ready")
            return None
        
        if not await runner.setup_test_environment():
            logger.error("❌ TEST: Failed to setup test environment")
            return None
        
        return await runner.run_suite(suite)


async def run_all_tests() -> Dict[str, List[TestResult]]:
    """Run all available test suites."""
    suite_names = list_available_suites()
    all_results = {}
    
    async with IntegrationTestRunner() as runner:
        if not await runner.wait_for_services():
            logger.error("❌ TEST: Services not ready")
            return {}
        
        if not await runner.setup_test_environment():
            logger.error("❌ TEST: Failed to setup test environment")
            return {}
        
        for suite_name in suite_names:
            logger.info(f"\nTEST: {'='*60}")
            suite = get_suite_by_name(suite_name)
            results = await runner.run_suite(suite)
            all_results[suite_name] = results
    
    return all_results


# Command-line interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        logger.info("TEST: Usage:")
        logger.info("TEST:   python integration_tests.py scenario <scenario_name>")
        logger.info("TEST:   python integration_tests.py suite <suite_name>")
        logger.info("TEST:   python integration_tests.py all")
        logger.info("TEST:   python integration_tests.py list")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        logger.info("TEST: Available scenarios:")
        for scenario in list_available_scenarios():
            logger.info(f"TEST:   - {scenario}")
        logger.info("TEST: \nAvailable suites:")
        for suite in list_available_suites():
            logger.info(f"TEST:   - {suite}")
    
    elif command == "scenario":
        if len(sys.argv) < 3:
            logger.error("TEST: Please specify scenario name")
            sys.exit(1)
        scenario_name = sys.argv[2]
        result = asyncio.run(run_single_scenario(scenario_name))
        sys.exit(0 if result and result.success else 1)
    
    elif command == "suite":
        if len(sys.argv) < 3:
            logger.error("TEST: Please specify suite name")
            sys.exit(1)
        suite_name = sys.argv[2]
        results = asyncio.run(run_test_suite(suite_name))
        if results:
            success = all(r.success for r in results)
            sys.exit(0 if success else 1)
        else:
            sys.exit(1)
    
    elif command == "all":
        all_results = asyncio.run(run_all_tests())
        if all_results:
            total_success = all(
                all(r.success for r in results)
                for results in all_results.values()
            )
            sys.exit(0 if total_success else 1)
        else:
            sys.exit(1)
    
    else:
        logger.error(f"TEST: Unknown command: {command}")
        sys.exit(1)
