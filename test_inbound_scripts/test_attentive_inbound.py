#!/usr/bin/env python3
"""
Test script for sending inbound Attentive messages to the vital-chatwoot-bridge REST API.

This script simulates various Attentive webhook events to test the bridge's 
Attentive message processing functionality including SMS and email messages.
"""

import requests
import json
import sys
import time
from datetime import datetime

# Configuration
BRIDGE_BASE_URL = "http://localhost:8009"
ATTENTIVE_WEBHOOK_ENDPOINT = "/api/v1/inboxes/attentive/webhook"
ATTENTIVE_EMAIL_ENDPOINT = "/api/v1/inboxes/attentive/email/inbound"

def create_attentive_webhook_payload(event_type, contact_info, message_content, message_id=None):
    """
    Create an Attentive webhook payload.
    
    Args:
        event_type: Type of event ("sms.sent", "email.sent", "sms.inbound_message")
        contact_info: Dict with contact details (email, phone_number, name)
        message_content: The message text
        message_id: Optional message ID
    
    Returns:
        dict: Attentive webhook payload
    """
    timestamp = int(datetime.now().timestamp())
    
    payload = {
        "type": event_type,
        "timestamp": timestamp,
        "company": {
            "id": "test_company_123",
            "name": "Test Company",
            "domain": "testcompany.com"
        },
        "subscriber": {
            "id": f"subscriber_{timestamp}",
            "email": contact_info.get("email"),
            "phone": contact_info.get("phone_number"),
            "first_name": contact_info.get("name", "").split(" ")[0] if contact_info.get("name") else None,
            "last_name": " ".join(contact_info.get("name", "").split(" ")[1:]) if contact_info.get("name") and " " in contact_info.get("name") else None,
            "created_at": timestamp - 86400,  # Created yesterday
            "attributes": {
                "source": "test_script",
                "opt_in_date": timestamp - 86400
            }
        },
        "message": {
            "id": message_id or f"msg_{event_type}_{timestamp}",
            "text": message_content,
            "created_at": timestamp,
            "channel": "email" if "email" in event_type else "sms",
            "direction": "inbound" if "inbound" in event_type else "outbound",
            "metadata": {
                "campaign_id": f"campaign_{timestamp}" if "sent" in event_type else None,
                "campaign_name": "Test Campaign" if "sent" in event_type else None,
                "subject": f"Test Subject: {message_content[:30]}..." if "email" in event_type else None
            }
        }
    }
    
    return payload

def create_email_reply_payload(contact_info, message_content, subject=None, reply_to_message_id=None):
    """
    Create an Attentive email reply payload.
    
    Args:
        contact_info: Dict with contact details
        message_content: Email content
        subject: Email subject
        reply_to_message_id: Original message ID being replied to
    
    Returns:
        dict: Email reply payload
    """
    return {
        "contact": {
            "email": contact_info.get("email"),
            "phone_number": contact_info.get("phone_number"),
            "name": contact_info.get("name")
        },
        "message_content": message_content,
        "subject": subject or f"Re: Test Email - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "from_email": contact_info.get("email"),
        "to_email": "support@testcompany.com",
        "reply_to_message_id": reply_to_message_id,
        "timestamp": datetime.now().isoformat(),
        "email_headers": {
            "Message-ID": f"<test_{int(time.time())}@testcustomer.com>",
            "In-Reply-To": f"<original_{reply_to_message_id}@attentive.com>" if reply_to_message_id else None,
            "References": f"<original_{reply_to_message_id}@attentive.com>" if reply_to_message_id else None
        }
    }

def send_webhook_message(payload, endpoint=ATTENTIVE_WEBHOOK_ENDPOINT):
    """
    Send a webhook message to the bridge API.
    
    Args:
        payload: Webhook payload
        endpoint: API endpoint to use
        
    Returns:
        requests.Response: API response
    """
    url = f"{BRIDGE_BASE_URL}{endpoint}"
    headers = {
        "Content-Type": "application/json"
    }
    
    print(f"🚀 Sending to: {url}")
    print(f"📤 Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending request: {e}")
        return None

def main():
    """Main test function."""
    print("=" * 70)
    print("🧪 Attentive Inbound Message Test Script")
    print("=" * 70)
    
    # Test scenarios for different Attentive message types
    test_scenarios = [
        {
            "name": "SMS Inbound Message",
            "type": "webhook",
            "event_type": "sms.inbound_message",
            "contact": {
                "phone_number": "+19179919685",
                "name": "John Doe"
            },
            "message": "Hi, I received your SMS and want to learn more about your services.",
            "description": "Customer replying to an SMS campaign"
        },
        {
            "name": "SMS Sent (Business to Customer)",
            "type": "webhook", 
            "event_type": "sms.sent",
            "contact": {
                "phone_number": "+19179919685",
                "name": "Jane Smith"
            },
            "message": "Thanks for signing up! Here's your 20% discount code: SAVE20",
            "description": "Business sending promotional SMS"
        },
        {
            "name": "Email Sent (Business to Customer)",
            "type": "webhook",
            "event_type": "email.sent", 
            "contact": {
                "email": "customer@example.com",
                "name": "Alice Johnson"
            },
            "message": "Welcome to our newsletter! Here are this week's top deals and updates.",
            "description": "Business sending marketing email"
        },
        {
            "name": "Email Reply (Customer Response)",
            "type": "email_reply",
            "contact": {
                "email": "customer@example.com", 
                "name": "Bob Wilson"
            },
            "message": "Thank you for the email! I'm interested in your premium plan. Can someone contact me to discuss pricing?",
            "subject": "Re: Premium Plan Inquiry",
            "description": "Customer replying to business email"
        },
        {
            "name": "Multi-Channel Contact (Email + Phone)",
            "type": "webhook",
            "event_type": "sms.inbound_message",
            "contact": {
                "email": "multi@example.com",
                "phone_number": "+19179919685", 
                "name": "Multi Channel User"
            },
            "message": "I have both email and phone. Please reach out via whichever is more convenient.",
            "description": "Contact with multiple communication channels"
        },
        {
            "name": "Support Request via SMS",
            "type": "webhook",
            "event_type": "sms.inbound_message",
            "contact": {
                "phone_number": "+19179919685",
                "name": "Support User"
            },
            "message": "I'm having trouble with my account login. Can you help me reset my password?",
            "description": "Customer support request via SMS"
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
                    print(f"  {i}. {scenario['name']}: {scenario['description']}")
                print(f"  0. Run all scenarios")
                return
        except ValueError:
            print("❌ Invalid scenario number format")
            print("Usage: python test_attentive_inbound.py [scenario_number]")
            print("  scenario_number: 0 for all, 1-6 for specific scenario")
            return
    else:
        # Default to running all scenarios if no argument provided
        scenarios_to_run = test_scenarios
        print("No scenario specified, running all scenarios...")
        print("Usage: python test_attentive_inbound.py [scenario_number]")
        print("  0 = Run all scenarios")
        for i, scenario in enumerate(test_scenarios, 1):
            print(f"  {i} = {scenario['name']}")
        print()
    
    # Run selected scenarios
    for i, scenario in enumerate(scenarios_to_run, 1):
        print(f"\n📋 Running Test {i}/{len(scenarios_to_run)}: {scenario['name']}")
        print("-" * 50)
        print(f"📝 Description: {scenario['description']}")
        
        # Create appropriate payload based on scenario type
        if scenario["type"] == "webhook":
            payload = create_attentive_webhook_payload(
                event_type=scenario["event_type"],
                contact_info=scenario["contact"],
                message_content=scenario["message"]
            )
            endpoint = ATTENTIVE_WEBHOOK_ENDPOINT
            
        elif scenario["type"] == "email_reply":
            payload = create_email_reply_payload(
                contact_info=scenario["contact"],
                message_content=scenario["message"],
                subject=scenario.get("subject")
            )
            endpoint = ATTENTIVE_EMAIL_ENDPOINT
        
        # Send the message
        response = send_webhook_message(payload, endpoint)
        
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
                print("✅ Message processed successfully!")
                
                # Extract key information
                chatwoot_result = response_data.get("data", {}).get("chatwoot_result", {})
                if chatwoot_result:
                    conversation = chatwoot_result.get("conversation", {})
                    message = chatwoot_result.get("message", {})
                    contact = chatwoot_result.get("contact", {})
                    
                    print(f"🗨️  Conversation ID: {conversation.get('id')}")
                    print(f"📨 Message ID: {message.get('id')}")
                    print(f"👤 Contact ID: {contact.get('id')}")
                    
                    # Show contact details
                    if contact.get('email'):
                        print(f"📧 Email: {contact.get('email')}")
                    if contact.get('phone_number'):
                        print(f"📞 Phone: {contact.get('phone_number')}")
                    
            else:
                print("❌ Message failed to process")
                error_detail = response_data.get("detail", {})
                if error_detail:
                    print(f"🔍 Error details: {error_detail}")
                    
        except json.JSONDecodeError:
            print(f"❌ Invalid JSON response: {response.text}")
        
        # Wait between scenarios if running multiple
        if len(scenarios_to_run) > 1 and i < len(scenarios_to_run):
            print("\n⏳ Waiting 3 seconds before next test...")
            time.sleep(3)
    
    print("\n" + "=" * 70)
    print("🏁 Attentive test completed!")
    print("💡 Tip: Check Chatwoot for new conversations and messages")
    print("=" * 70)

if __name__ == "__main__":
    main()
