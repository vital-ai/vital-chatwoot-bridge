"""
Predefined test scenarios for the Vital Chatwoot Bridge.
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

from vital_chatwoot_bridge.agents.models import MockAgentBehavior


class TestScenarioType(str, Enum):
    """Types of test scenarios."""
    SYNC_RESPONSE = "sync_response"
    ASYNC_RESPONSE = "async_response"
    ERROR_HANDLING = "error_handling"
    INBOX_ROUTING = "inbox_routing"
    LOAD_TEST = "load_test"


class TestMessage(BaseModel):
    """Test message configuration."""
    content: str = Field(..., description="Message content")
    expected_response_pattern: str = Field(..., description="Expected response pattern (regex)")
    delay_before_send: float = Field(default=0.0, description="Delay before sending message")


class TestScenario(BaseModel):
    """Test scenario configuration."""
    name: str = Field(..., description="Scenario name")
    description: str = Field(..., description="Scenario description")
    scenario_type: TestScenarioType = Field(..., description="Scenario type")
    inbox_id: str = Field(..., description="Inbox ID to use")
    agent_behavior: MockAgentBehavior = Field(default=MockAgentBehavior.ECHO, description="Mock agent behavior")
    messages: List[TestMessage] = Field(..., description="Messages to send")
    expected_responses: int = Field(..., description="Expected number of responses")
    timeout_seconds: int = Field(default=10, description="Scenario timeout")
    setup_commands: List[str] = Field(default=[], description="Setup commands to run")
    cleanup_commands: List[str] = Field(default=[], description="Cleanup commands to run")


# Predefined test scenarios
BASIC_ECHO_SCENARIO = TestScenario(
    name="basic_echo",
    description="Basic echo test with immediate response",
    scenario_type=TestScenarioType.SYNC_RESPONSE,
    inbox_id="1",
    agent_behavior=MockAgentBehavior.ECHO,
    messages=[
        TestMessage(
            content="Hello, this is a test message",
            expected_response_pattern=r"Echo: Hello, this is a test message"
        )
    ],
    expected_responses=1,
    timeout_seconds=10
)

CONVERSATION_FLOW_SCENARIO = TestScenario(
    name="conversation_flow",
    description="Multi-message conversation flow",
    scenario_type=TestScenarioType.SYNC_RESPONSE,
    inbox_id="1",
    agent_behavior=MockAgentBehavior.TEST,
    messages=[
        TestMessage(
            content="Hello",
            expected_response_pattern=r"Hello! I'm a mock AI agent.*"
        ),
        TestMessage(
            content="I need help with my order",
            expected_response_pattern=r"I can assist you with various tasks.*",
            delay_before_send=1.0
        ),
        TestMessage(
            content="Thank you, goodbye",
            expected_response_pattern=r"Thank you for chatting with me.*",
            delay_before_send=1.0
        )
    ],
    expected_responses=3,
    timeout_seconds=20
)

DELAYED_RESPONSE_SCENARIO = TestScenario(
    name="delayed_response",
    description="Test async response handling with delayed agent",
    scenario_type=TestScenarioType.ASYNC_RESPONSE,
    inbox_id="2",
    agent_behavior=MockAgentBehavior.DELAY,
    messages=[
        TestMessage(
            content="This should trigger a delayed response",
            expected_response_pattern=r"Delayed response after \d+s:.*"
        )
    ],
    expected_responses=1,
    timeout_seconds=60
)

ERROR_RECOVERY_SCENARIO = TestScenario(
    name="error_recovery",
    description="Test error handling when agent fails",
    scenario_type=TestScenarioType.ERROR_HANDLING,
    inbox_id="3",
    agent_behavior=MockAgentBehavior.ERROR,
    messages=[
        TestMessage(
            content="This should trigger an error",
            expected_response_pattern=r"I apologize.*encountered an error.*"
        )
    ],
    expected_responses=1,
    timeout_seconds=15
)

INBOX_ROUTING_SCENARIO = TestScenario(
    name="inbox_routing",
    description="Test that messages from different inboxes route to correct agents",
    scenario_type=TestScenarioType.INBOX_ROUTING,
    inbox_id="1",  # Test with inbox 1
    messages=[
        TestMessage(
            content="Message to inbox 1",
            expected_response_pattern=r"Echo: Message to inbox 1"
        )
    ],
    expected_responses=1,  # One response for one message
    timeout_seconds=20
)

LOAD_TEST_SCENARIO = TestScenario(
    name="load_test",
    description="Load test with multiple concurrent messages",
    scenario_type=TestScenarioType.LOAD_TEST,
    inbox_id="1",
    agent_behavior=MockAgentBehavior.ECHO,
    messages=[
        TestMessage(
            content=f"Load test message {i}",
            expected_response_pattern=f"Echo: Load test message {i}",
            delay_before_send=0.1 * i
        ) for i in range(10)
    ],
    expected_responses=10,
    timeout_seconds=30
)

RANDOM_BEHAVIOR_SCENARIO = TestScenario(
    name="random_behavior",
    description="Test random agent behavior with mixed responses",
    scenario_type=TestScenarioType.SYNC_RESPONSE,
    inbox_id="4",
    agent_behavior=MockAgentBehavior.RANDOM,
    messages=[
        TestMessage(
            content=f"Random test message {i}",
            expected_response_pattern=r".*test message.*",  # Flexible pattern for random responses
            delay_before_send=0.5
        ) for i in range(5)
    ],
    expected_responses=5,
    timeout_seconds=45
)

# Collection of all predefined scenarios
PREDEFINED_SCENARIOS = [
    BASIC_ECHO_SCENARIO,
    CONVERSATION_FLOW_SCENARIO,
    DELAYED_RESPONSE_SCENARIO,
    ERROR_RECOVERY_SCENARIO,
    INBOX_ROUTING_SCENARIO,
    LOAD_TEST_SCENARIO,
    RANDOM_BEHAVIOR_SCENARIO
]


class TestSuite(BaseModel):
    """Test suite containing multiple scenarios."""
    name: str = Field(..., description="Test suite name")
    description: str = Field(..., description="Test suite description")
    scenarios: List[TestScenario] = Field(..., description="Test scenarios")
    parallel_execution: bool = Field(default=False, description="Run scenarios in parallel")
    stop_on_failure: bool = Field(default=True, description="Stop suite on first failure")


# Predefined test suites
SMOKE_TEST_SUITE = TestSuite(
    name="smoke_tests",
    description="Basic smoke tests for core functionality",
    scenarios=[
        BASIC_ECHO_SCENARIO,
        CONVERSATION_FLOW_SCENARIO
    ],
    parallel_execution=False,
    stop_on_failure=True
)

COMPREHENSIVE_TEST_SUITE = TestSuite(
    name="comprehensive_tests",
    description="Comprehensive test suite covering all scenarios",
    scenarios=PREDEFINED_SCENARIOS,
    parallel_execution=False,
    stop_on_failure=False
)

PERFORMANCE_TEST_SUITE = TestSuite(
    name="performance_tests",
    description="Performance and load testing scenarios",
    scenarios=[
        LOAD_TEST_SCENARIO,
        RANDOM_BEHAVIOR_SCENARIO
    ],
    parallel_execution=True,
    stop_on_failure=False
)

ERROR_HANDLING_TEST_SUITE = TestSuite(
    name="error_handling_tests",
    description="Error handling and recovery scenarios",
    scenarios=[
        ERROR_RECOVERY_SCENARIO,
        DELAYED_RESPONSE_SCENARIO
    ],
    parallel_execution=False,
    stop_on_failure=False
)


def get_scenario_by_name(name: str) -> TestScenario:
    """Get a test scenario by name."""
    for scenario in PREDEFINED_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise ValueError(f"Test scenario '{name}' not found")


def get_suite_by_name(name: str) -> TestSuite:
    """Get a test suite by name."""
    suites = {
        "smoke": SMOKE_TEST_SUITE,
        "comprehensive": COMPREHENSIVE_TEST_SUITE,
        "performance": PERFORMANCE_TEST_SUITE,
        "error_handling": ERROR_HANDLING_TEST_SUITE
    }
    
    if name not in suites:
        raise ValueError(f"Test suite '{name}' not found. Available: {list(suites.keys())}")
    
    return suites[name]


def list_available_scenarios() -> List[str]:
    """List all available test scenario names."""
    return [scenario.name for scenario in PREDEFINED_SCENARIOS]


def list_available_suites() -> List[str]:
    """List all available test suite names."""
    return ["smoke", "comprehensive", "performance", "error_handling"]
