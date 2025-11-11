#!/usr/bin/env python3
"""
Test script for sending inbound LoopMessage messages to the vital-chatwoot-bridge REST API.

This script simulates an inbound message from LoopMessage API to test the 
bridge's inbound message processing functionality.
"""

import requests
import json
import sys
from datetime import datetime

# Configuration
BRIDGE_BASE_URL = "http://localhost:8009"
LOOPMESSAGE_INBOUND_ENDPOINT = "/api/v1/inboxes/loopmessage/messages/inbound"

def create_test_message(phone_number="+19179919685", name="Test User", message_content="Hello, this is a test message!", message_type="imessage"):
    """
    Create a test LoopMessage inbound message payload.
    
    Args:
        phone_number: Customer's phone number
        name: Customer's name
        message_content: The message text
        message_type: Type of message (imessage or sms)
    
    Returns:
        dict: LoopMessage inbound payload
    """
    return {
        "contact": {
            "phone_number": phone_number,
            "name": name
        },
        "message_content": message_content,
        "message_type": message_type
    }

def send_inbound_message(payload):
    """
    Send an inbound message to the bridge API.
    
    Args:
        payload: LoopMessage inbound payload
        
    Returns:
        requests.Response: API response
    """
    url = f"{BRIDGE_BASE_URL}{LOOPMESSAGE_INBOUND_ENDPOINT}"
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"🚀 Sending inbound LoopMessage to: {url}")
    print(f"📤 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending request: {e}")
        return None

def main():
    """Main test function."""
    print("=" * 60)
    print("🧪 LoopMessage Inbound Message Test Script")
    print("=" * 60)
    
    # Test scenarios
    test_scenarios = [
        {
            "name": "Basic Test Message",
            "phone_number": "+19179919685",
            "customer_name": "Test User",
            "message": "Hello, this is a test message!",
            "type": "imessage"
        },
        {
            "name": "Loan Request",
            "phone_number": "+19179919685", 
            "customer_name": "John Doe",
            "message": "Hello, help me get a loan.",
            "type": "imessage"
        },
        {
            "name": "Customer Support",
            "phone_number": "+19179919685",
            "customer_name": "Jane Smith", 
            "message": "I need help with my account. Can someone assist me?",
            "type": "imessage"
        }
    ]
    
    # Command line argument handling
    if len(sys.argv) > 1:
        try:
            scenario_choice = int(sys.argv[1])
            if scenario_choice == 0:
                scenarios_to_run = test_scenarios
            elif 1 <= scenario_choice <= len(test_scenarios):
                scenarios_to_run = [test_scenarios[scenario_choice - 1]]
            else:
                print(f"❌ Invalid scenario number. Choose 0-{len(test_scenarios)}")
                print("Available scenarios:")
                for i, scenario in enumerate(test_scenarios, 1):
                    print(f"  {i}. {scenario['name']}: \"{scenario['message']}\"")
                print(f"  0. Run all scenarios")
                return
        except ValueError:
            print("❌ Invalid scenario number format")
            print("Usage: python test_loopmessage_inbound.py [scenario_number]")
            print("  scenario_number: 0 for all, 1-3 for specific scenario")
            return
    else:
        # Default to running all scenarios if no argument provided
        scenarios_to_run = test_scenarios
        print("No scenario specified, running all scenarios...")
        print("Usage: python test_loopmessage_inbound.py [scenario_number]")
        print("  0 = Run all scenarios")
        for i, scenario in enumerate(test_scenarios, 1):
            print(f"  {i} = {scenario['name']}")
        print()
    
    # Run selected scenarios
    for i, scenario in enumerate(scenarios_to_run, 1):
        print(f"\n📋 Running Test {i}/{len(scenarios_to_run)}: {scenario['name']}")
        print("-" * 40)
        
        # Create test payload
        payload = create_test_message(
            phone_number=scenario['phone_number'],
            name=scenario['customer_name'],
            message_content=scenario['message'],
            message_type=scenario['type']
        )
        
        # Send the message
        response = send_inbound_message(payload)
        
        if response is None:
            print("❌ Failed to send request")
            continue
            
        # Process response
        print(f"📥 Response Status: {response.status_code}")
        
        try:
            response_data = response.json()
            print(f"📄 Response Body:")
            print(json.dumps(response_data, indent=2))
            
            if response.status_code == 200 and response_data.get("success"):
                print("✅ Message sent successfully!")
                
                # Extract key information
                chatwoot_result = response_data.get("data", {}).get("chatwoot_result", {})
                if chatwoot_result:
                    conversation = chatwoot_result.get("conversation", {})
                    message = chatwoot_result.get("message", {})
                    
                    print(f"🗨️  Conversation ID: {conversation.get('id')}")
                    print(f"📨 Message ID: {message.get('id')}")
                    print(f"📞 Phone: {conversation.get('contact', {}).get('phone_number')}")
                    
            else:
                print("❌ Message failed to send")
                
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON response: {response.text}")
        
        # Wait between scenarios if running multiple
        if len(scenarios_to_run) > 1 and i < len(scenarios_to_run):
            print("\n⏳ Waiting 2 seconds before next test...")
            import time
            time.sleep(2)
    
    print("\n" + "=" * 60)
    print("🏁 Test completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
