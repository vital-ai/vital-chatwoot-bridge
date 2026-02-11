#!/usr/bin/env python3
"""
Chatwoot Contact Management CLI Script
Simple command line interface for managing contacts via Chatwoot Application API

Usage: python chatwoot_contact_manager.py <command> [options]

Commands:
  list-contacts       List all contacts with pagination
  search-contacts     Search contacts by various criteria
  count-contacts      Count total contacts
  count-conversations Count total conversations
  get-contact         Get detailed information about a specific contact
  list-conversations  List conversations for a specific contact
  get-messages        Get all messages for a specific conversation
  merge-contacts      Merge two duplicate contacts

Examples:
  python chatwoot_contact_manager.py list-contacts --page 1 --per-page 25
  python chatwoot_contact_manager.py search-contacts --email "john@cardiff.co"
  python chatwoot_contact_manager.py search-contacts --name "John" --query "cardiff"
  python chatwoot_contact_manager.py count-contacts
  python chatwoot_contact_manager.py count-conversations
  python chatwoot_contact_manager.py get-contact --contact-id 1314 --include-conversations
  python chatwoot_contact_manager.py get-contact --contact-id 1314 --include-conversations --status resolved --date-from 2025-11-01
  python chatwoot_contact_manager.py get-contact --contact-id 1314 --include-conversations --message-type incoming --sort-by created_at --order desc
  python chatwoot_contact_manager.py list-conversations --contact-id 1314 --status pending --show-messages
  python chatwoot_contact_manager.py get-messages --conversation-id 1151 --page 1 --per-page 10
  python chatwoot_contact_manager.py merge-contacts --primary-id 123 --secondary-id 456
"""

import requests
import argparse
import json
import os
import sys
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from datetime import datetime


class ChatwootContactManager:
    """Simple Chatwoot contact management using Application API"""
    
    def __init__(self):
        """Initialize with ContactManagement app credentials"""
        # Load .env from parent directory (project root)
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
        
        self.base_url = os.getenv('CW_BRIDGE__chatwoot__base_url')
        # Use existing working user token for Application API access
        self.contact_token = os.getenv('CW_BRIDGE__chatwoot__user_access_token')
        self.account_id = os.getenv('CW_BRIDGE__chatwoot__account_id')
        
        # Validate required environment variables
        if not all([self.base_url, self.contact_token, self.account_id]):
            print("❌ Error: Missing required environment variables:")
            print("   CW_BRIDGE__chatwoot__base_url, CW_BRIDGE__chatwoot__user_access_token, CW_BRIDGE__chatwoot__account_id")
            sys.exit(1)
        
        # Set up requests session with authentication
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'api_access_token': self.contact_token
        })
        
        print(f"🔗 Connected to: {self.base_url}")
        print(f"📋 Account ID: {self.account_id}")
        print()
    
    def _make_request(self, method: str, endpoint: str, params: dict = None, data: dict = None) -> dict:
        """Make authenticated API request with error handling"""
        # Contacts use Application API endpoints, not Platform API
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/{endpoint}"
        
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, params=params)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data, params=params)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP Error {response.status_code}: {response.text}")
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"❌ Request Error: {str(e)}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ JSON Decode Error: {str(e)}")
            sys.exit(1)
    
    def _format_date(self, date_string) -> str:
        """Format ISO date string or Unix timestamp to readable format"""
        try:
            if not date_string or date_string == 'N/A':
                return 'N/A'
            if isinstance(date_string, (int, float)):
                dt = datetime.fromtimestamp(date_string)
                return dt.strftime('%Y-%m-%d')
            if not isinstance(date_string, str):
                return str(date_string)[:10]
            dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d')
        except:
            return str(date_string)[:10] if date_string else 'N/A'
    
    def _print_contacts_table(self, contacts: List[dict], title: str = "Contacts"):
        """Print contacts in a formatted table"""
        if not contacts:
            print(f"No contacts found.")
            return
        
        print(f"{title}:")
        print()
        print(f"{'ID':<6} {'Name':<20} {'Email':<30} {'Phone':<15} {'Created':<12}")
        print("-" * 85)
        
        for contact in contacts:
            contact_id = str(contact.get('id', 'N/A'))
            name = (contact.get('name') or 'N/A')[:19]
            email = (contact.get('email') or 'N/A')[:29]
            phone = (contact.get('phone_number') or 'N/A')[:14]
            created = self._format_date(contact.get('created_at', 'N/A'))
            
            print(f"{contact_id:<6} {name:<20} {email:<30} {phone:<15} {created:<12}")
    
    def list_contacts(self, page: int = 1, per_page: int = 25, sort: str = 'name') -> dict:
        """List contacts with pagination"""
        print(f"📋 Listing contacts (Page {page}, {per_page} per page, sorted by {sort})...")
        
        params = {
            'page': page,
            'per_page': min(per_page, 100),  # API max is 100
            'sort': sort
        }
        
        result = self._make_request('GET', 'contacts', params=params)
        
        contacts = result.get('payload', [])
        meta = result.get('meta', {})
        
        self._print_contacts_table(contacts, f"Contacts (Page {page})")
        
        # Print pagination info
        total_count = meta.get('count', len(contacts))
        total_pages = meta.get('total_pages', 1)
        current_page = meta.get('current_page', page)
        
        print()
        print(f"Total: {total_count} contacts (Page {current_page} of {total_pages})")
        
        return result
    
    def search_contacts(self, query: str = None, email: str = None, 
                       phone: str = None, name: str = None) -> dict:
        """Search contacts using the correct Chatwoot search API"""
        
        if not any([query, email, phone, name]):
            print("❌ Error: At least one search criteria must be provided")
            sys.exit(1)
        
        # Build search parameters according to Chatwoot API docs
        params = {}
        search_terms = []
        
        # Use the 'q' parameter for general search (supports name, identifier, email, phone)
        search_value = query or email or phone or name
        params['q'] = search_value
        
        if query:
            search_terms.append(f'query="{query}"')
        if email:
            search_terms.append(f'email="{email}"')
        if phone:
            search_terms.append(f'phone="{phone}"')
        if name:
            search_terms.append(f'name="{name}"')
        
        search_description = ", ".join(search_terms)
        print(f"🔍 Searching contacts by {search_description}...")
        
        result = self._make_request('GET', 'contacts/search', params=params)
        
        contacts = result.get('payload', [])
        
        if contacts:
            self._print_contacts_table(contacts, f"Search Results ({len(contacts)} found)")
        else:
            print("No contacts found matching the search criteria.")
        
        return result
    
    def count_contacts(self, filter_criteria: str = None) -> int:
        """Count total contacts"""
        print("🔢 Counting contacts...")
        
        params = {}
        if filter_criteria:
            params['q'] = filter_criteria
            print(f"   Filter: {filter_criteria}")
        
        result = self._make_request('GET', 'contacts', params=params)
        
        meta = result.get('meta', {})
        total_count = meta.get('count', len(result.get('payload', [])))
        
        if filter_criteria:
            print(f"Total contacts matching '{filter_criteria}': {total_count}")
        else:
            print(f"Total contacts: {total_count}")
        
        return total_count
    
    def count_conversations(self) -> int:
        """Count total conversations in the account"""
        print("🔢 Counting conversations...")
        
        try:
            # Check counts for different statuses to see if we're missing some
            statuses = ['all', 'open', 'resolved', 'pending', 'snoozed']
            status_counts = {}
            
            for status in statuses:
                params = {'status': status} if status != 'all' else {}
                result = self._make_request('GET', 'conversations/meta', params=params)
                meta = result.get('meta', {})
                status_counts[status] = meta.get('all_count', 0)
                print(f"  {status.capitalize()} conversations: {status_counts[status]}")
            
            # Also get the default (no status filter) count
            result = self._make_request('GET', 'conversations/meta')
            meta = result.get('meta', {})
            all_count = meta.get('all_count', 0)
            mine_count = meta.get('mine_count', 0)
            unassigned_count = meta.get('unassigned_count', 0)
            assigned_count = meta.get('assigned_count', 0)
            
            print(f"\nDefault (no filter): {all_count}")
            print(f"  - My conversations: {mine_count}")
            print(f"  - Assigned: {assigned_count}")
            print(f"  - Unassigned: {unassigned_count}")
            
            # Calculate total across all statuses
            total_by_status = sum(status_counts[s] for s in ['open', 'resolved', 'pending', 'snoozed'])
            print(f"\nSum of all statuses: {total_by_status}")
            print(f"**Returning true total: {total_by_status}**")
            
            return total_by_status
            
        except Exception as e:
            print(f"❌ Error counting conversations: {str(e)}")
            sys.exit(1)
    
    def get_contact_details(self, contact_id: int, include_conversations: bool = False, 
                           conversations_page: int = 1, conversations_per_page: int = 25,
                           date_from: str = None, date_to: str = None,
                           status: str = None, assignee_type: str = None,
                           inbox_id: int = None, labels: str = None,
                           message_type: str = None, sort_by: str = None,
                           order: str = None) -> dict:
        """Get detailed information about a specific contact"""
        print(f"🔍 Getting details for contact {contact_id}...")
        
        # Get basic contact information
        contact_result = self._make_request('GET', f'contacts/{contact_id}')
        contact = contact_result.get('payload', {})
        
        print(f"\n📋 Contact Details:")
        print(f"   ID: {contact.get('id', 'N/A')}")
        print(f"   Name: {contact.get('name') or 'N/A'}")
        print(f"   Email: {contact.get('email') or 'N/A'}")
        print(f"   Phone: {contact.get('phone_number') or 'N/A'}")
        print(f"   Created: {self._format_date(contact.get('created_at'))}")
        print(f"   Updated: {self._format_date(contact.get('updated_at'))}")
        
        # Show custom attributes if any
        custom_attrs = contact.get('custom_attributes', {})
        if custom_attrs:
            print(f"\n🏷️  Custom Attributes:")
            for key, value in custom_attrs.items():
                print(f"   {key}: {value}")
        
        # Show labels if any
        labels = contact.get('labels', [])
        if labels:
            print(f"\n🏷️  Labels: {', '.join(labels)}")
        
        # Show contact inboxes
        contact_inboxes = contact.get('contact_inboxes', [])
        if contact_inboxes:
            print(f"\n📥 Inboxes:")
            for inbox in contact_inboxes:
                inbox_name = inbox.get('inbox', {}).get('name', 'Unknown')
                source_id = inbox.get('source_id', 'N/A')
                print(f"   {inbox_name} (Source ID: {source_id})")
        
        # Get conversations if requested
        if include_conversations:
            print(f"\n💬 Getting conversations (Page {conversations_page}, {conversations_per_page} per page)...")
            
            conv_params = {
                'page': conversations_page,
                'per_page': conversations_per_page
            }
            
            # Add all available filters if provided
            if date_from:
                conv_params['created_at_since'] = date_from
            if date_to:
                conv_params['created_at_until'] = date_to
            if status:
                conv_params['status'] = status
            if assignee_type:
                conv_params['assignee_type'] = assignee_type
            if inbox_id:
                conv_params['inbox_id'] = inbox_id
            if labels:
                conv_params['labels'] = labels
            if message_type:
                conv_params['message_type'] = message_type
            if sort_by:
                conv_params['sort_by'] = sort_by
            if order:
                conv_params['order'] = order
            
            try:
                conversations_result = self._make_request('GET', f'contacts/{contact_id}/conversations', params=conv_params)
                conversations = conversations_result.get('payload', [])
                
                if conversations:
                    print(f"\n💬 Conversations ({len(conversations)} found):")
                    for conv in conversations[:5]:  # Show first 5 conversations
                        conv_id = conv.get('id', 'N/A')
                        status = conv.get('status', 'N/A')
                        created = self._format_date(conv.get('created_at'))
                        inbox_name = conv.get('inbox', {}).get('name', 'Unknown')
                        
                        # Get last message preview
                        messages = conv.get('messages', [])
                        last_message = ""
                        if messages:
                            last_msg = messages[-1]
                            content = last_msg.get('content', '')
                            last_message = content[:50] + "..." if len(content) > 50 else content
                        
                        print(f"   Conv {conv_id}: {status} | {inbox_name} | {created}")
                        if last_message:
                            print(f"      Last: {last_message}")
                else:
                    print(f"   No conversations found")
                    
            except Exception as e:
                print(f"   ⚠️  Could not retrieve conversations: {str(e)}")
        
        return contact_result
    
    def list_conversations(self, contact_id: int, page: int = 1, per_page: int = 25,
                          date_from: str = None, date_to: str = None,
                          status: str = None, assignee_type: str = None,
                          inbox_id: int = None, labels: str = None,
                          message_type: str = None, sort_by: str = None,
                          order: str = None, show_messages: bool = False,
                          messages_limit: int = 3) -> dict:
        """List conversations for a specific contact"""
        print(f"💬 Listing conversations for contact {contact_id}...")
        
        conv_params = {
            'page': page,
            'per_page': per_page
        }
        
        # Add all available filters if provided
        if date_from:
            conv_params['created_at_since'] = date_from
        if date_to:
            conv_params['created_at_until'] = date_to
        if status:
            conv_params['status'] = status
        if assignee_type:
            conv_params['assignee_type'] = assignee_type
        if inbox_id:
            conv_params['inbox_id'] = inbox_id
        if labels:
            conv_params['labels'] = labels
        if message_type:
            conv_params['message_type'] = message_type
        if sort_by:
            conv_params['sort_by'] = sort_by
        if order:
            conv_params['order'] = order
        
        # Show active filters
        active_filters = []
        if status:
            active_filters.append(f"status={status}")
        if date_from or date_to:
            date_range = f"{date_from or 'start'} to {date_to or 'end'}"
            active_filters.append(f"dates={date_range}")
        if message_type:
            active_filters.append(f"type={message_type}")
        if inbox_id:
            active_filters.append(f"inbox={inbox_id}")
        
        if active_filters:
            print(f"   Filters: {', '.join(active_filters)}")
        
        try:
            result = self._make_request('GET', f'contacts/{contact_id}/conversations', params=conv_params)
            conversations = result.get('payload', [])
            meta = result.get('meta', {})
            
            if not conversations:
                print("   No conversations found.")
                return result
            
            # Print conversations table
            print(f"\n📋 Conversations (Page {page}, {len(conversations)} found):")
            print()
            print(f"{'ID':<8} {'Status':<10} {'Inbox':<20} {'Created':<12} {'Updated':<12} {'Messages':<8}")
            print("-" * 80)
            
            for conv in conversations:
                conv_id = str(conv.get('id', 'N/A'))
                status_val = conv.get('status', 'N/A')
                inbox_name = conv.get('inbox', {}).get('name', 'Unknown')[:19]
                created = self._format_date(conv.get('created_at'))
                updated = self._format_date(conv.get('updated_at'))
                msg_count = len(conv.get('messages', []))
                
                print(f"{conv_id:<8} {status_val:<10} {inbox_name:<20} {created:<12} {updated:<12} {msg_count:<8}")
                
                # Show recent messages if requested
                if show_messages and conv.get('messages'):
                    messages = conv['messages'][-messages_limit:]  # Get last N messages
                    for i, msg in enumerate(messages):
                        sender_type = msg.get('sender_type', 'unknown')
                        sender_name = 'Agent' if sender_type == 'User' else 'Contact'
                        content = msg.get('content', '')[:60]
                        msg_created = self._format_date(msg.get('created_at'))
                        
                        prefix = "   └─" if i == len(messages) - 1 else "   ├─"
                        print(f"{prefix} {sender_name}: {content}... ({msg_created})")
                    print()
            
            # Show pagination info
            total_count = meta.get('count', len(conversations))
            total_pages = (total_count + per_page - 1) // per_page
            print(f"\nTotal: {total_count} conversations (Page {page} of {total_pages})")
            
            return result
            
        except Exception as e:
            print(f"❌ Error retrieving conversations: {str(e)}")
            sys.exit(1)
    
    def get_messages(self, conversation_id: int, contact_id: int, page: int = 1, per_page: int = 25,
                    before_id: int = None, after_id: int = None,
                    message_type: str = None, show_content: bool = True) -> dict:
        """Get all messages for a specific conversation via contact"""
        print(f"💬 Getting messages for conversation {conversation_id} via contact {contact_id}...")
        
        # Show active filters
        active_filters = []
        if message_type:
            active_filters.append(f"type={message_type}")
        if before_id:
            active_filters.append(f"before={before_id}")
        if after_id:
            active_filters.append(f"after={after_id}")
        
        if active_filters:
            print(f"   Filters: {', '.join(active_filters)}")
        
        try:
            # Use the correct API endpoint - get conversations via contact
            result = self._make_request('GET', f'contacts/{contact_id}/conversations')
            conversations = result.get('payload', [])
            
            # Find the specific conversation
            conversation = None
            for conv in conversations:
                if conv.get('id') == conversation_id:
                    conversation = conv
                    break
            
            if not conversation:
                print(f"   Conversation {conversation_id} not found for contact {contact_id}.")
                return {'error': 'Conversation not found'}
            
            # Show conversation context
            print(f"\n📋 Conversation Details:")
            print(f"   ID: {conversation.get('id', 'N/A')}")
            print(f"   Status: {conversation.get('status', 'N/A')}")
            print(f"   Inbox: {conversation.get('inbox', {}).get('name', 'Unknown')}")
            print(f"   Created: {self._format_date(conversation.get('created_at'))}")
            
            # Get messages from conversation
            messages = conversation.get('messages', [])
            
            if not messages:
                print("\n   No messages found in this conversation.")
                return result
            
            # Apply client-side filtering if needed (API might not support all filters)
            filtered_messages = messages
            if message_type:
                filtered_messages = [msg for msg in messages if msg.get('message_type') == message_type]
            
            # Apply pagination (client-side since conversation API returns all messages)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_messages = filtered_messages[start_idx:end_idx]
            
            # Print messages
            print(f"\n💬 Messages (Page {page}, {len(paginated_messages)} of {len(filtered_messages)} shown):")
            print()
            
            for i, msg in enumerate(paginated_messages):
                msg_id = msg.get('id', 'N/A')
                sender_type = msg.get('sender_type', 'unknown')
                sender_name = 'Agent' if sender_type == 'User' else 'Contact'
                msg_type = msg.get('message_type', 'N/A')
                created = self._format_date(msg.get('created_at'))
                content = msg.get('content', '')
                
                # Get sender details if available
                sender = msg.get('sender', {})
                if sender and sender.get('name'):
                    sender_name = f"{sender_name} ({sender.get('name')})"
                elif sender and sender.get('email'):
                    sender_name = f"{sender_name} ({sender.get('email')})"
                
                print(f"{'='*80}")
                print(f"Message {msg_id} | {sender_name} | {msg_type} | {created}")
                print(f"{'='*80}")
                
                if show_content:
                    # Handle different content types
                    if content:
                        print(content)
                    else:
                        print("[No text content]")
                    
                    # Show attachments if any
                    attachments = msg.get('attachments', [])
                    if attachments:
                        print(f"\n📎 Attachments ({len(attachments)}):")
                        for att in attachments:
                            att_type = att.get('file_type', 'unknown')
                            att_name = att.get('data_url', 'unnamed')
                            print(f"   - {att_name} ({att_type})")
                else:
                    print(f"[Content: {len(content)} characters]")
                
                print()
            
            # Show pagination info
            total_pages = (len(filtered_messages) + per_page - 1) // per_page
            print(f"Total: {len(filtered_messages)} messages (Page {page} of {total_pages})")
            
            return result
            
        except Exception as e:
            print(f"❌ Error retrieving messages: {str(e)}")
            sys.exit(1)
    
    def test_conversation_params(self, contact_id: int) -> dict:
        """Test different conversation API parameters to see what's available"""
        print(f"🧪 Testing conversation API parameters for contact {contact_id}...")
        
        # Test basic call to see response structure
        try:
            basic_result = self._make_request('GET', f'contacts/{contact_id}/conversations')
            print(f"\n📋 Basic API Response Structure:")
            
            if 'payload' in basic_result:
                conversations = basic_result['payload']
                if conversations:
                    first_conv = conversations[0]
                    print(f"   Conversation keys: {list(first_conv.keys())}")
                    
                    if 'messages' in first_conv and first_conv['messages']:
                        first_message = first_conv['messages'][0]
                        print(f"   Message keys: {list(first_message.keys())}")
            
            # Test with various parameters to see what works
            test_params = [
                {'status': 'open'},
                {'status': 'resolved'},
                {'status': 'pending'}, 
                {'assignee_type': 'agent'},
                {'assignee_type': 'team'},
                {'inbox_id': 1},
                {'labels': 'test'},
                {'sort_by': 'created_at'},
                {'sort_by': 'updated_at'},
                {'order': 'asc'},
                {'order': 'desc'},
                {'message_type': 'incoming'},
                {'message_type': 'outgoing'},
                {'created_at_since': '2025-01-01'},
                {'created_at_until': '2025-12-31'},
                {'updated_at_since': '2025-01-01'},
                {'updated_at_until': '2025-12-31'}
            ]
            
            print(f"\n🧪 Testing parameters:")
            working_params = []
            
            for params in test_params:
                try:
                    result = self._make_request('GET', f'contacts/{contact_id}/conversations', params=params)
                    param_name = list(params.keys())[0]
                    param_value = list(params.values())[0]
                    print(f"   ✅ {param_name}={param_value} - Works")
                    working_params.append(params)
                except Exception as e:
                    param_name = list(params.keys())[0] 
                    param_value = list(params.values())[0]
                    print(f"   ❌ {param_name}={param_value} - Error: {str(e)[:50]}...")
            
            print(f"\n✅ Working parameters: {len(working_params)}")
            return {'working_params': working_params, 'basic_result': basic_result}
            
        except Exception as e:
            print(f"❌ Error testing parameters: {str(e)}")
            return {}
    
    def merge_contacts(self, primary_id: int, secondary_id: int) -> dict:
        """Merge two contacts"""
        print(f"🔄 Merging contact {secondary_id} into contact {primary_id}...")
        
        # First, get details of both contacts to show what we're merging
        try:
            primary_contact = self._make_request('GET', f'contacts/{primary_id}')
            secondary_contact = self._make_request('GET', f'contacts/{secondary_id}')
            
            print(f"   Primary contact: {primary_contact.get('payload', {}).get('name', 'Unknown')} ({primary_contact.get('payload', {}).get('email', 'No email')})")
            print(f"   Secondary contact: {secondary_contact.get('payload', {}).get('name', 'Unknown')} ({secondary_contact.get('payload', {}).get('email', 'No email')})")
            
        except Exception as e:
            print(f"❌ Error: Could not retrieve contact details. Please verify contact IDs exist.")
            sys.exit(1)
        
        # Perform the merge
        merge_data = {
            'child_contact_id': secondary_id
        }
        
        result = self._make_request('POST', f'contacts/{primary_id}/merge', data=merge_data)
        
        print("✅ Successfully merged contacts!")
        print(f"   - Contact {secondary_id} has been merged into contact {primary_id}")
        print(f"   - All conversations and data from contact {secondary_id} have been transferred")
        print(f"   - Contact {secondary_id} has been deleted")
        
        return result


def main():
    """CLI interface for contact management"""
    parser = argparse.ArgumentParser(
        description='Chatwoot Contact Management CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list-contacts --page 1 --per-page 25
  %(prog)s search-contacts --email "john@cardiff.co"
  %(prog)s search-contacts --name "John" --query "cardiff"
  %(prog)s count-contacts
  %(prog)s merge-contacts --primary-id 123 --secondary-id 456
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List contacts command
    list_parser = subparsers.add_parser('list-contacts', help='List all contacts')
    list_parser.add_argument('--page', type=int, default=1, help='Page number (default: 1)')
    list_parser.add_argument('--per-page', type=int, default=25, help='Records per page (default: 25, max: 100)')
    list_parser.add_argument('--sort', default='name', choices=['name', 'email', 'phone_number', 'created_at'], 
                           help='Sort field (default: name)')
    
    # Search contacts command
    search_parser = subparsers.add_parser('search-contacts', help='Search contacts')
    search_parser.add_argument('--query', help='General search query (searches name, email, phone)')
    search_parser.add_argument('--email', help='Search by email address')
    search_parser.add_argument('--phone', help='Search by phone number')
    search_parser.add_argument('--name', help='Search by name')
    
    # Count contacts command
    count_parser = subparsers.add_parser('count-contacts', help='Count total contacts')
    count_parser.add_argument('--filter', help='Optional filter criteria')
    
    # Count conversations command
    count_conv_parser = subparsers.add_parser('count-conversations', help='Count total conversations')
    
    # Get contact details command
    details_parser = subparsers.add_parser('get-contact', help='Get detailed contact information')
    details_parser.add_argument('--contact-id', type=int, required=True, help='Contact ID to get details for')
    details_parser.add_argument('--include-conversations', action='store_true', help='Include conversation history')
    details_parser.add_argument('--conv-page', type=int, default=1, help='Conversation page number (default: 1)')
    details_parser.add_argument('--conv-per-page', type=int, default=25, help='Conversations per page (default: 25)')
    
    # Date filters
    details_parser.add_argument('--date-from', help='Filter conversations from date (YYYY-MM-DD)')
    details_parser.add_argument('--date-to', help='Filter conversations to date (YYYY-MM-DD)')
    
    # Status and assignment filters
    details_parser.add_argument('--status', choices=['open', 'resolved', 'pending'], help='Filter by conversation status')
    details_parser.add_argument('--assignee-type', choices=['agent', 'team'], help='Filter by assignment type')
    
    # Inbox and label filters
    details_parser.add_argument('--inbox-id', type=int, help='Filter by specific inbox ID')
    details_parser.add_argument('--labels', help='Filter by conversation labels')
    
    # Message type and sorting
    details_parser.add_argument('--message-type', choices=['incoming', 'outgoing'], help='Filter by message direction')
    details_parser.add_argument('--sort-by', choices=['created_at', 'updated_at'], help='Sort conversations by field')
    details_parser.add_argument('--order', choices=['asc', 'desc'], help='Sort order (default: desc)')
    
    # List conversations command
    conv_parser = subparsers.add_parser('list-conversations', help='List conversations for a specific contact')
    conv_parser.add_argument('--contact-id', type=int, required=True, help='Contact ID to list conversations for')
    conv_parser.add_argument('--page', type=int, default=1, help='Page number (default: 1)')
    conv_parser.add_argument('--per-page', type=int, default=25, help='Conversations per page (default: 25)')
    conv_parser.add_argument('--show-messages', action='store_true', help='Show recent messages in each conversation')
    conv_parser.add_argument('--messages-limit', type=int, default=3, help='Number of recent messages to show (default: 3)')
    
    # Date filters
    conv_parser.add_argument('--date-from', help='Filter conversations from date (YYYY-MM-DD)')
    conv_parser.add_argument('--date-to', help='Filter conversations to date (YYYY-MM-DD)')
    
    # Status and assignment filters
    conv_parser.add_argument('--status', choices=['open', 'resolved', 'pending'], help='Filter by conversation status')
    conv_parser.add_argument('--assignee-type', choices=['agent', 'team'], help='Filter by assignment type')
    
    # Inbox and label filters
    conv_parser.add_argument('--inbox-id', type=int, help='Filter by specific inbox ID')
    conv_parser.add_argument('--labels', help='Filter by conversation labels')
    
    # Message type and sorting
    conv_parser.add_argument('--message-type', choices=['incoming', 'outgoing'], help='Filter by message direction')
    conv_parser.add_argument('--sort-by', choices=['created_at', 'updated_at'], help='Sort conversations by field')
    conv_parser.add_argument('--order', choices=['asc', 'desc'], help='Sort order (default: desc)')
    
    # Get messages command
    messages_parser = subparsers.add_parser('get-messages', help='Get all messages for a specific conversation')
    messages_parser.add_argument('--conversation-id', type=int, required=True, help='Conversation ID to get messages for')
    messages_parser.add_argument('--contact-id', type=int, required=True, help='Contact ID that owns the conversation')
    messages_parser.add_argument('--page', type=int, default=1, help='Page number (default: 1)')
    messages_parser.add_argument('--per-page', type=int, default=25, help='Messages per page (default: 25)')
    messages_parser.add_argument('--before-id', type=int, help='Get messages before this message ID')
    messages_parser.add_argument('--after-id', type=int, help='Get messages after this message ID')
    messages_parser.add_argument('--message-type', choices=['incoming', 'outgoing'], help='Filter by message direction')
    messages_parser.add_argument('--no-content', action='store_true', help='Hide message content (show only headers)')
    
    # Test conversation parameters command
    test_parser = subparsers.add_parser('test-conv-params', help='Test available conversation API parameters')
    test_parser.add_argument('--contact-id', type=int, required=True, help='Contact ID to test with')
    
    # Merge contacts command
    merge_parser = subparsers.add_parser('merge-contacts', help='Merge two duplicate contacts')
    merge_parser.add_argument('--primary-id', type=int, required=True, 
                            help='Primary contact ID (this contact will be kept)')
    merge_parser.add_argument('--secondary-id', type=int, required=True, 
                            help='Secondary contact ID (this contact will be merged and deleted)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize contact manager
    manager = ChatwootContactManager()
    
    try:
        # Execute the requested command
        if args.command == 'list-contacts':
            manager.list_contacts(
                page=args.page,
                per_page=args.per_page,
                sort=args.sort
            )
            
        elif args.command == 'search-contacts':
            manager.search_contacts(
                query=args.query,
                email=args.email,
                phone=args.phone,
                name=args.name
            )
            
        elif args.command == 'count-contacts':
            manager.count_contacts(filter_criteria=args.filter)
            
        elif args.command == 'count-conversations':
            manager.count_conversations()
            
        elif args.command == 'get-contact':
            manager.get_contact_details(
                contact_id=args.contact_id,
                include_conversations=args.include_conversations,
                conversations_page=args.conv_page,
                conversations_per_page=args.conv_per_page,
                date_from=args.date_from,
                date_to=args.date_to,
                status=args.status,
                assignee_type=getattr(args, 'assignee_type', None),
                inbox_id=getattr(args, 'inbox_id', None),
                labels=args.labels,
                message_type=getattr(args, 'message_type', None),
                sort_by=getattr(args, 'sort_by', None),
                order=args.order
            )
            
        elif args.command == 'list-conversations':
            manager.list_conversations(
                contact_id=args.contact_id,
                page=args.page,
                per_page=getattr(args, 'per_page', 25),
                date_from=args.date_from,
                date_to=args.date_to,
                status=args.status,
                assignee_type=getattr(args, 'assignee_type', None),
                inbox_id=getattr(args, 'inbox_id', None),
                labels=args.labels,
                message_type=getattr(args, 'message_type', None),
                sort_by=getattr(args, 'sort_by', None),
                order=args.order,
                show_messages=getattr(args, 'show_messages', False),
                messages_limit=getattr(args, 'messages_limit', 3)
            )
            
        elif args.command == 'get-messages':
            manager.get_messages(
                conversation_id=getattr(args, 'conversation_id'),
                contact_id=getattr(args, 'contact_id'),
                page=args.page,
                per_page=getattr(args, 'per_page', 25),
                before_id=getattr(args, 'before_id', None),
                after_id=getattr(args, 'after_id', None),
                message_type=getattr(args, 'message_type', None),
                show_content=not getattr(args, 'no_content', False)
            )
            
        elif args.command == 'test-conv-params':
            manager.test_conversation_params(contact_id=args.contact_id)
            
        elif args.command == 'merge-contacts':
            manager.merge_contacts(
                primary_id=args.primary_id,
                secondary_id=args.secondary_id
            )
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
