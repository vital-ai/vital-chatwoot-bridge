#!/usr/bin/env python3
"""
Chatwoot Application API Manager

This script uses the Application API to access existing accounts and users.
Unlike the Platform API, this can access all data in your Chatwoot instance.

Usage:
    python chatwoot_app_api.py --help
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException


@dataclass
class AppAPIConfig:
    """Configuration for Chatwoot Application API connection."""
    base_url: str
    user_token: str
    account_id: int
    
    def __post_init__(self):
        # Remove trailing slash from base_url
        self.base_url = self.base_url.rstrip('/')


class ChatwootAppAPIError(Exception):
    """Custom exception for Chatwoot Application API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


class ChatwootAppAPIManager:
    """Manages Chatwoot data via Application APIs."""
    
    def __init__(self, config: AppAPIConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'api_access_token': config.user_token
        })
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make an API request to Chatwoot Application API."""
        # Application API endpoints are account-specific
        url = f"{self.config.base_url}/api/v1/accounts/{self.config.account_id}{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data)
            elif method.upper() == 'PUT':
                response = self.session.put(url, json=data)
            elif method.upper() == 'DELETE':
                response = self.session.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Handle different response status codes
            if response.status_code in [200, 201]:
                return response.json() if response.content else {}
            elif response.status_code == 404:
                raise ChatwootAppAPIError(
                    f"Resource not found: {endpoint}",
                    status_code=response.status_code
                )
            elif response.status_code == 401:
                raise ChatwootAppAPIError(
                    "Unauthorized: Check your user access token",
                    status_code=response.status_code
                )
            else:
                error_data = None
                try:
                    error_data = response.json()
                except:
                    pass
                
                raise ChatwootAppAPIError(
                    f"API request failed with status {response.status_code}: {response.text}",
                    status_code=response.status_code,
                    response_data=error_data
                )
                
        except RequestException as e:
            raise ChatwootAppAPIError(f"Network error: {str(e)}")
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all agents in the account."""
        return self._make_request('GET', '/agents')
    
    def get_agent(self, agent_id: int) -> Dict[str, Any]:
        """Get details of a specific agent."""
        return self._make_request('GET', f'/agents/{agent_id}')
    
    def create_agent(self, name: str, email: str, role: str = 'agent', 
                    skip_invitation: bool = False) -> Dict[str, Any]:
        """
        Create a new agent in the account.
        
        Args:
            name: Full name of the agent
            email: Email address
            role: Role ('agent' or 'administrator')
            skip_invitation: If True, attempt to create without invitation
        """
        agent_data = {
            "name": name,
            "email": email,
            "role": role,
            "availability_status": "available",
            "auto_offline": True
        }
        
        # Based on API docs, try different parameter combinations
        if skip_invitation:
            # Try various parameters that might suppress invitation
            agent_data.update({
                "confirmed": True,
                "skip_invitation": True,
                "send_invitation": False,
                "auto_offline": False
            })
        
        return self._make_request('POST', '/agents', agent_data)
    
    def update_agent(self, agent_id: int, name: Optional[str] = None, 
                    role: Optional[str] = None) -> Dict[str, Any]:
        """Update an agent's details."""
        agent_data = {}
        if name:
            agent_data["name"] = name
        if role:
            agent_data["role"] = role
        
        return self._make_request('PUT', f'/agents/{agent_id}', agent_data)
    
    def delete_agent(self, agent_id: int) -> bool:
        """Delete an agent from the account."""
        try:
            self._make_request('DELETE', f'/agents/{agent_id}')
            return True
        except ChatwootAppAPIError:
            return False
    
    def list_contacts(self) -> List[Dict[str, Any]]:
        """List all contacts in the account."""
        return self._make_request('GET', '/contacts')
    
    def get_contact(self, contact_id: int) -> Dict[str, Any]:
        """Get details of a specific contact."""
        return self._make_request('GET', f'/contacts/{contact_id}')
    
    def list_conversations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List conversations in the account.
        
        Args:
            status: Filter by status ('open', 'resolved', 'pending')
        """
        endpoint = '/conversations'
        if status:
            endpoint += f'?status={status}'
        
        return self._make_request('GET', endpoint)
    
    def get_account_summary(self) -> Dict[str, Any]:
        """Get a summary of account statistics."""
        try:
            agents = self.list_agents()
            contacts_resp = self.list_contacts()
            conversations_resp = self.list_conversations()
            
            # Extract lists/counts from API responses (may be dicts with payload/data keys)
            contacts_list = contacts_resp.get('payload', contacts_resp) if isinstance(contacts_resp, dict) else contacts_resp
            contacts_count = contacts_resp.get('meta', {}).get('count', len(contacts_list)) if isinstance(contacts_resp, dict) else len(contacts_list)
            
            conv_list = conversations_resp.get('data', {}).get('payload', []) if isinstance(conversations_resp, dict) else conversations_resp
            if not isinstance(conv_list, list):
                conv_list = conversations_resp.get('payload', []) if isinstance(conversations_resp, dict) else []
            conv_count = len(conv_list)
            
            return {
                "account_id": self.config.account_id,
                "agents_count": len(agents) if isinstance(agents, list) else 0,
                "contacts_count": contacts_count,
                "conversations_count": conv_count,
                "agents": agents if isinstance(agents, list) else [],
                "recent_conversations": conv_list[:5] if conv_list else []
            }
        except Exception as e:
            return {"error": str(e)}


def load_app_config_from_env() -> AppAPIConfig:
    """Load Application API configuration from environment variables."""
    # Try to load from .env file
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    except ImportError:
        pass
    
    base_url = os.getenv('CHATWOOT_BASE_URL')
    user_token = os.getenv('CHATWOOT_USER_ACCESS_TOKEN')
    account_id = os.getenv('CHATWOOT_ACCOUNT_ID')
    
    if not base_url:
        raise ValueError("CHATWOOT_BASE_URL environment variable is required")
    if not user_token:
        raise ValueError("CHATWOOT_USER_ACCESS_TOKEN environment variable is required")
    if not account_id:
        raise ValueError("CHATWOOT_ACCOUNT_ID environment variable is required")
    
    try:
        account_id = int(account_id)
    except ValueError:
        raise ValueError("CHATWOOT_ACCOUNT_ID must be a valid integer")
    
    return AppAPIConfig(base_url=base_url, user_token=user_token, account_id=account_id)


def print_agents_table(agents: List[Dict[str, Any]]):
    """Print agents in a formatted table."""
    if not agents:
        print("No agents found.")
        return
    
    print(f"{'ID':<5} {'Name':<25} {'Email':<30} {'Role':<15} {'Status':<10}")
    print("-" * 85)
    
    for agent in agents:
        availability = agent.get('availability', 'N/A')
        print(f"{agent.get('id', 'N/A'):<5} {agent.get('name', 'N/A'):<25} {agent.get('email', 'N/A'):<30} {agent.get('role', 'N/A'):<15} {availability:<10}")


def main():
    """Main function to handle command line interface."""
    parser = argparse.ArgumentParser(description='Chatwoot Application API Manager')
    parser.add_argument('--base-url', help='Chatwoot base URL (default: from env)')
    parser.add_argument('--user-token', help='User access token (default: from env)')
    parser.add_argument('--account-id', type=int, help='Account ID (default: from env)')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List agents command
    subparsers.add_parser('list-agents', help='List all agents in the account')
    
    # Get agent command
    get_agent_parser = subparsers.add_parser('get-agent', help='Get agent details')
    get_agent_parser.add_argument('--agent-id', type=int, required=True, help='Agent ID')
    
    # Create agent command
    create_agent_parser = subparsers.add_parser('create-agent', help='Create a new agent')
    create_agent_parser.add_argument('--name', required=True, help='Full name')
    create_agent_parser.add_argument('--email', required=True, help='Email address')
    create_agent_parser.add_argument('--role', choices=['agent', 'administrator'], default='agent', help='Role')
    create_agent_parser.add_argument('--skip-invitation', action='store_true', help='Skip sending invitation email')
    
    # Update agent command
    update_agent_parser = subparsers.add_parser('update-agent', help='Update agent details')
    update_agent_parser.add_argument('--agent-id', type=int, required=True, help='Agent ID')
    update_agent_parser.add_argument('--name', help='New name')
    update_agent_parser.add_argument('--role', choices=['agent', 'administrator'], help='New role')
    
    # Delete agent command
    delete_agent_parser = subparsers.add_parser('delete-agent', help='Delete an agent')
    delete_agent_parser.add_argument('--agent-id', type=int, required=True, help='Agent ID')
    
    # List contacts command
    subparsers.add_parser('list-contacts', help='List all contacts')
    
    # List conversations command
    list_conv_parser = subparsers.add_parser('list-conversations', help='List conversations')
    list_conv_parser.add_argument('--status', choices=['open', 'resolved', 'pending'], help='Filter by status')
    
    # Account summary command
    subparsers.add_parser('account-summary', help='Get account summary')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        # Load configuration
        if args.base_url and args.user_token and args.account_id:
            config = AppAPIConfig(base_url=args.base_url, user_token=args.user_token, account_id=args.account_id)
        else:
            config = load_app_config_from_env()
        
        # Initialize manager
        manager = ChatwootAppAPIManager(config)
        
        # Execute commands
        if args.command == 'list-agents':
            print(f"📋 Listing agents for account {config.account_id}...")
            agents = manager.list_agents()
            print_agents_table(agents)
        
        elif args.command == 'get-agent':
            print(f"👤 Getting agent {args.agent_id}...")
            agent = manager.get_agent(args.agent_id)
            print(json.dumps(agent, indent=2))
        
        elif args.command == 'create-agent':
            print(f"➕ Creating agent {args.name}...")
            agent = manager.create_agent(args.name, args.email, args.role, args.skip_invitation)
            print("Agent created successfully!")
            if args.skip_invitation:
                print("(Invitation email was suppressed)")
            print(json.dumps(agent, indent=2))
        
        elif args.command == 'update-agent':
            print(f"✏️  Updating agent {args.agent_id}...")
            agent = manager.update_agent(args.agent_id, args.name, args.role)
            print("Agent updated successfully!")
            print(json.dumps(agent, indent=2))
        
        elif args.command == 'delete-agent':
            success = manager.delete_agent(args.agent_id)
            if success:
                print(f"Agent {args.agent_id} deleted successfully!")
            else:
                print(f"Failed to delete agent {args.agent_id}")
        
        elif args.command == 'list-contacts':
            print(f"📞 Listing contacts for account {config.account_id}...")
            contacts = manager.list_contacts()
            print(f"Found {len(contacts)} contacts:")
            for contact in contacts[:10]:  # Show first 10
                print(f"  ID: {contact.get('id')}, Name: {contact.get('name')}, Email: {contact.get('email')}")
            if len(contacts) > 10:
                print(f"  ... and {len(contacts) - 10} more")
        
        elif args.command == 'list-conversations':
            status_text = f" with status '{args.status}'" if args.status else ""
            print(f"💬 Listing conversations{status_text} for account {config.account_id}...")
            conversations = manager.list_conversations(args.status)
            print(f"Found {len(conversations)} conversations:")
            for conv in conversations[:10]:  # Show first 10
                print(f"  ID: {conv.get('id')}, Status: {conv.get('status')}, Messages: {conv.get('messages_count', 0)}")
            if len(conversations) > 10:
                print(f"  ... and {len(conversations) - 10} more")
        
        elif args.command == 'account-summary':
            print(f"📊 Getting summary for account {config.account_id}...")
            summary = manager.get_account_summary()
            if 'error' in summary:
                print(f"Error: {summary['error']}")
            else:
                print(f"Account ID: {summary['account_id']}")
                print(f"Agents: {summary['agents_count']}")
                print(f"Contacts: {summary['contacts_count']}")
                print(f"Conversations: {summary['conversations_count']}")
                
                if summary['agents']:
                    print("\nAgents:")
                    print_agents_table(summary['agents'])
    
    except ChatwootAppAPIError as e:
        print(f"Chatwoot API Error: {e.message}")
        if e.status_code:
            print(f"Status Code: {e.status_code}")
        if e.response_data:
            print(f"Response Data: {json.dumps(e.response_data, indent=2)}")
        sys.exit(1)
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
