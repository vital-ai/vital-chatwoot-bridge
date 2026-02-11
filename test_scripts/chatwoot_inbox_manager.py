#!/usr/bin/env python3
"""
Chatwoot Inbox Manager — List inboxes and post messages (SMS/email).

Uses the Chatwoot Application API to list inboxes and post messages
directly to conversations within those inboxes.

Usage:
    python chatwoot_inbox_manager.py list-inboxes
    python chatwoot_inbox_manager.py post-message --json '{"inbox_type":"sms",...}'
    python chatwoot_inbox_manager.py post-message --file payload.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


@dataclass
class AppAPIConfig:
    """Configuration for Chatwoot Application API connection."""
    base_url: str
    user_token: str
    account_id: int

    def __post_init__(self):
        self.base_url = self.base_url.rstrip('/')


class ChatwootInboxError(Exception):
    """Custom exception for Chatwoot Inbox API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


class ChatwootInboxManager:
    """Manages Chatwoot inboxes and message posting via Application API."""

    def __init__(self, config: AppAPIConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'api_access_token': config.user_token
        })

    def _api_url(self, endpoint: str) -> str:
        """Build account-scoped API URL."""
        return f"{self.config.base_url}/api/v1/accounts/{self.config.account_id}{endpoint}"

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None,
                      params: Optional[Dict] = None) -> Any:
        """Make an API request to Chatwoot Application API."""
        url = self._api_url(endpoint)

        try:
            response = self.session.request(method, url, json=data, params=params)

            if response.status_code in [200, 201]:
                return response.json() if response.content else {}
            elif response.status_code == 401:
                raise ChatwootInboxError("Unauthorized: Check your user access token", status_code=401)
            elif response.status_code == 404:
                raise ChatwootInboxError(f"Resource not found: {endpoint}", status_code=404)
            else:
                error_data = None
                try:
                    error_data = response.json()
                except Exception:
                    pass
                raise ChatwootInboxError(
                    f"API request failed with status {response.status_code}: {response.text}",
                    status_code=response.status_code,
                    response_data=error_data
                )

        except RequestException as e:
            raise ChatwootInboxError(f"Network error: {str(e)}")

    # ── Inbox operations ─────────────────────────────────────────────

    def list_inboxes(self) -> List[Dict[str, Any]]:
        """List all inboxes in the account."""
        result = self._make_request('GET', '/inboxes')
        # Response may be {"payload": [...]} or a raw list
        if isinstance(result, dict):
            return result.get('payload', result.get('data', []))
        return result

    def get_inbox(self, inbox_id: int) -> Dict[str, Any]:
        """Get details for a specific inbox."""
        return self._make_request('GET', f'/inboxes/{inbox_id}')

    # ── Contact operations ───────────────────────────────────────────

    def search_contact(self, query: str) -> Optional[Dict[str, Any]]:
        """Search for a contact by phone, email, or identifier."""
        result = self._make_request('GET', '/contacts/search', params={'q': query})
        contacts = result.get('payload', []) if isinstance(result, dict) else result
        return contacts[0] if contacts else None

    def create_contact(self, inbox_id: int, identifier: str,
                       name: Optional[str] = None, email: Optional[str] = None,
                       phone_number: Optional[str] = None) -> Dict[str, Any]:
        """Create a new contact in the given inbox. Returns full contact with contact_inboxes."""
        payload = {"inbox_id": inbox_id, "identifier": identifier}
        if name:
            payload["name"] = name
        if email:
            payload["email"] = email
        if phone_number:
            payload["phone_number"] = phone_number

        result = self._make_request('POST', '/contacts', data=payload)
        # Response may be {"payload": {"contact": {...}}} or {"payload": {...}} or flat
        if isinstance(result, dict):
            contact_data = result.get('payload', result)
            if isinstance(contact_data, dict) and 'contact' in contact_data:
                contact_data = contact_data['contact']
            return contact_data
        return result

    def get_contact(self, contact_id: int) -> Dict[str, Any]:
        """Get full contact details including contact_inboxes."""
        result = self._make_request('GET', f'/contacts/{contact_id}')
        if isinstance(result, dict):
            return result.get('payload', result) if 'payload' in result else result
        return result

    def get_source_id_for_inbox(self, contact: Dict[str, Any], inbox_id: int) -> Optional[str]:
        """Extract the source_id for a specific inbox from a contact's contact_inboxes."""
        contact_inboxes = contact.get('contact_inboxes', [])
        for ci in contact_inboxes:
            inbox = ci.get('inbox', {})
            if inbox.get('id') == inbox_id:
                source_id = ci.get('source_id')
                logger.info(f"Found source_id '{source_id}' for inbox {inbox_id}")
                return source_id
        return None

    def get_or_create_contact(self, inbox_id: int, contact_info: Dict[str, Any]) -> Dict[str, Any]:
        """Find existing contact or create a new one. Ensures contact_inbox exists for the target inbox."""
        identifier = contact_info.get('identifier', '')
        search_key = contact_info.get('phone_number') or contact_info.get('email') or identifier

        if search_key:
            existing = self.search_contact(search_key)
            if existing:
                logger.info(f"Found existing contact: ID={existing.get('id', 'N/A')}, Name={existing.get('name', 'N/A')}")
                # Get full contact details with contact_inboxes
                full_contact = self.get_contact(existing['id'])
                source_id = self.get_source_id_for_inbox(full_contact, inbox_id)
                if source_id:
                    full_contact['_source_id'] = source_id
                    return full_contact
                # No contact_inbox for this inbox — create one by re-creating contact with inbox_id
                logger.info(f"No contact_inbox for inbox {inbox_id}, creating one")
                new_contact = self.create_contact(
                    inbox_id=inbox_id,
                    identifier=identifier,
                    name=contact_info.get('name'),
                    email=contact_info.get('email'),
                    phone_number=contact_info.get('phone_number')
                )
                # The response should have contact_inboxes with the new source_id
                source_id = self.get_source_id_for_inbox(new_contact, inbox_id)
                if source_id:
                    new_contact['_source_id'] = source_id
                else:
                    # Fetch again to get contact_inboxes
                    full_contact = self.get_contact(new_contact.get('id', existing['id']))
                    source_id = self.get_source_id_for_inbox(full_contact, inbox_id)
                    full_contact['_source_id'] = source_id
                    return full_contact
                return new_contact

        logger.info(f"Creating new contact: {identifier}")
        contact = self.create_contact(
            inbox_id=inbox_id,
            identifier=identifier,
            name=contact_info.get('name'),
            email=contact_info.get('email'),
            phone_number=contact_info.get('phone_number')
        )
        source_id = self.get_source_id_for_inbox(contact, inbox_id)
        if not source_id:
            # Fetch to get contact_inboxes
            full_contact = self.get_contact(contact['id'])
            source_id = self.get_source_id_for_inbox(full_contact, inbox_id)
            full_contact['_source_id'] = source_id
            logger.info(f"Created contact: ID={full_contact.get('id', 'N/A')}, source_id={source_id}")
            return full_contact
        contact['_source_id'] = source_id
        logger.info(f"Created contact: ID={contact.get('id', 'N/A')}, source_id={source_id}")
        return contact

    # ── Conversation operations ──────────────────────────────────────

    def find_open_conversation(self, contact_id: int, inbox_id: int) -> Optional[Dict[str, Any]]:
        """Find an existing open conversation for a contact in a specific inbox."""
        result = self._make_request('GET', f'/contacts/{contact_id}/conversations')
        conversations = result.get('payload', []) if isinstance(result, dict) else result
        if not isinstance(conversations, list):
            return None

        for conv in conversations:
            if (conv.get('inbox_id') == inbox_id and
                    conv.get('status') in ['open', 'pending']):
                return conv
        return None

    def create_conversation(self, inbox_id: int, contact_id: int,
                            source_id: Optional[str] = None,
                            custom_attributes: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new conversation."""
        payload = {
            "source_id": source_id or f"contact_{contact_id}",
            "inbox_id": inbox_id,
            "contact_id": contact_id,
            "custom_attributes": custom_attributes or {}
        }
        return self._make_request('POST', '/conversations', data=payload)

    def get_or_create_conversation(self, inbox_id: int, contact_id: int,
                                   conversation_id: Optional[int] = None,
                                   source_id: Optional[str] = None) -> Dict[str, Any]:
        """Find existing open conversation or create a new one."""
        if conversation_id:
            conv = self._make_request('GET', f'/conversations/{conversation_id}')
            logger.info(f"Using specified conversation: ID={conversation_id}")
            return conv

        existing = self.find_open_conversation(contact_id, inbox_id)
        if existing:
            logger.info(f"Found open conversation: ID={existing['id']}, Status={existing.get('status')}")
            return existing

        logger.info(f"Creating new conversation for contact {contact_id} in inbox {inbox_id}")
        return self.create_conversation(inbox_id, contact_id, source_id=source_id)

    # ── Message operations ───────────────────────────────────────────

    def send_message(self, conversation_id: int, content: str,
                     message_type: str = "incoming", content_type: str = "text",
                     extra_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a message to a conversation."""
        payload = {
            "content": content,
            "message_type": message_type,
            "content_type": content_type,
            "private": False
        }
        if extra_params:
            payload.update(extra_params)
        return self._make_request('POST', f'/conversations/{conversation_id}/messages', data=payload)

    # ── Full post-message flow ───────────────────────────────────────

    def post_message(self, message_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full flow: resolve inbox → find/create contact → find/create conversation → send message.

        Expected payload:
        {
            "inbox_type": "sms" | "email",
            "inbox_id": 123,              // either inbox_id or inbox_type required
            "contact": {
                "identifier": "+15551234567",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone_number": "+15551234567"
            },
            "message": {
                "content": "Hello!",
                "message_type": "incoming",
                "content_type": "text"
            },
            "conversation_id": null
        }
        """
        # Step 0: Resolve inbox
        inbox_id = message_payload.get('inbox_id')
        inbox_type = message_payload.get('inbox_type')

        if not inbox_id and not inbox_type:
            raise ChatwootInboxError("Either 'inbox_id' or 'inbox_type' is required")

        if not inbox_id:
            inbox_id = self._resolve_inbox_id(inbox_type)

        logger.info(f"Posting message to inbox {inbox_id}")

        # Step 1: Find or create contact
        contact_info = message_payload.get('contact', {})
        # Auto-fill phone_number or email from identifier based on inbox_type
        if inbox_type == 'sms' and not contact_info.get('phone_number'):
            contact_info['phone_number'] = contact_info.get('identifier')
        if inbox_type == 'email' and not contact_info.get('email'):
            contact_info['email'] = contact_info.get('identifier')

        logger.info(f"Resolving contact: {contact_info.get('identifier', 'N/A')}")
        contact = self.get_or_create_contact(inbox_id, contact_info)
        contact_id = contact['id']

        # Step 2: Find or create conversation
        # Use source_id from contact_inbox (generated by Chatwoot when contact is linked to inbox)
        source_id = contact.get('_source_id')
        if not source_id:
            logger.warning(f"No source_id found for contact {contact_id} in inbox {inbox_id}")
        else:
            logger.info(f"Using source_id: {source_id}")
        conversation_id = message_payload.get('conversation_id')
        conversation = self.get_or_create_conversation(inbox_id, contact_id, conversation_id, source_id=source_id)
        conv_id = conversation.get('id') or conversation.get('payload', {}).get('id')

        # Step 3: Send message
        msg = message_payload.get('message', {})
        content = msg.get('content', '')
        message_type = msg.get('message_type', 'incoming')
        content_type = msg.get('content_type', 'text')

        # For email inboxes, to_emails is a top-level param (comma-separated string)
        extra_params = {}
        email = contact_info.get('email')
        if email:
            extra_params['to_emails'] = email
            logger.info(f"Setting to_emails: {email}")

        logger.info(f"Sending {message_type} message to conversation {conv_id}")
        result = self.send_message(conv_id, content, message_type, content_type,
                                   extra_params=extra_params if extra_params else None)

        logger.info(f"Message sent successfully")
        return {
            "contact_id": contact_id,
            "conversation_id": conv_id,
            "message": result,
            "status": "success"
        }

    def _resolve_inbox_id(self, inbox_type: str) -> int:
        """Resolve inbox_type to a numeric inbox_id by scanning available inboxes."""
        inboxes = self.list_inboxes()
        type_map = {
            'sms': ['sms', 'api'],
            'email': ['email', 'api'],
            'imessage': ['api'],
            'api': ['api'],
            'web': ['web', 'website'],
        }
        channel_types = type_map.get(inbox_type.lower(), [inbox_type.lower()])

        for inbox in inboxes:
            channel = inbox.get('channel_type', '').lower().replace('channel::', '')
            if channel in channel_types:
                logger.info(f"Resolved inbox_type '{inbox_type}' -> inbox ID {inbox['id']} ({inbox.get('name')})")
                return inbox['id']

        inbox_list = ', '.join(str(i.get('id', '?')) + ':' + str(i.get('name', '?')) for i in inboxes)
        raise ChatwootInboxError(
            f"No inbox found for type '{inbox_type}'. Available inboxes: {inbox_list}"
        )


# ── CLI ──────────────────────────────────────────────────────────────

def load_config() -> AppAPIConfig:
    """Load configuration from environment."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    except ImportError:
        pass

    base_url = os.getenv('CW_BRIDGE__chatwoot__base_url')
    user_token = os.getenv('CW_BRIDGE__chatwoot__user_access_token')
    account_id = os.getenv('CW_BRIDGE__chatwoot__account_id')

    if not base_url:
        raise ValueError("CW_BRIDGE__chatwoot__base_url environment variable is required")
    if not user_token:
        raise ValueError("CW_BRIDGE__chatwoot__user_access_token environment variable is required")
    if not account_id:
        raise ValueError("CW_BRIDGE__chatwoot__account_id environment variable is required")

    return AppAPIConfig(base_url=base_url, user_token=user_token, account_id=int(account_id))


def print_inboxes(inboxes: List[Dict[str, Any]]):
    """Pretty-print inbox listing."""
    if not inboxes:
        logger.info("No inboxes found.")
        return

    logger.info(f"{'ID':<6} {'Name':<30} {'Channel Type':<25} {'Enabled':<8}")
    logger.info("-" * 75)
    for inbox in inboxes:
        inbox_id = inbox.get('id', 'N/A')
        name = inbox.get('name', 'N/A')[:28]
        channel = inbox.get('channel_type', 'N/A').replace('Channel::', '')
        enabled = '✅' if inbox.get('channel', {}).get('enabled', True) else '❌'
        logger.info(f"{inbox_id:<6} {name:<30} {channel:<25} {enabled:<8}")

    logger.info(f"Total: {len(inboxes)} inboxes")


def main():
    parser = argparse.ArgumentParser(
        description='Chatwoot Inbox Manager — list inboxes and post messages'
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # list-inboxes
    sub_list = subparsers.add_parser('list-inboxes', help='List all inboxes in the account')
    sub_list.add_argument('--verbose', '-v', action='store_true', help='Show full JSON response')

    # post-message
    sub_post = subparsers.add_parser('post-message', help='Post a message to an inbox')
    msg_group = sub_post.add_mutually_exclusive_group(required=True)
    msg_group.add_argument('--json', '-j', type=str, help='JSON payload string')
    msg_group.add_argument('--file', '-f', type=str, help='Path to JSON payload file')
    sub_post.add_argument('--dry-run', action='store_true', help='Show resolved payload without sending')

    # example-payloads
    subparsers.add_parser('example-payloads', help='Print example SMS and email JSON payloads')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'example-payloads':
        print_example_payloads()
        return

    try:
        config = load_config()
        manager = ChatwootInboxManager(config)
        logger.info(f"Connected to {config.base_url} (account {config.account_id})")

        if args.command == 'list-inboxes':
            inboxes = manager.list_inboxes()
            if args.verbose:
                logger.info(json.dumps(inboxes, indent=2, default=str))
            else:
                print_inboxes(inboxes)

        elif args.command == 'post-message':
            if args.json:
                payload = json.loads(args.json)
            else:
                with open(args.file, 'r') as f:
                    payload = json.load(f)

            logger.info(f"Payload: {json.dumps(payload, indent=2)}")

            if args.dry_run:
                logger.info("Dry run — no message sent.")
                return

            result = manager.post_message(payload)
            logger.info(f"Result: {json.dumps(result, indent=2, default=str)}")

    except ChatwootInboxError as e:
        logger.error(f"Chatwoot API Error: {e.message}")
        if e.status_code:
            logger.error(f"Status code: {e.status_code}")
        if e.response_data:
            logger.error(f"Response: {json.dumps(e.response_data, indent=2)}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


def print_example_payloads():
    """Print example SMS and email payloads."""
    sms_example = {
        "inbox_type": "sms",
        "contact": {
            "identifier": "+15551234567",
            "name": "Jane Doe"
        },
        "message": {
            "content": "Hello, I need help with my account",
            "message_type": "incoming"
        },
        "conversation_id": None
    }

    email_example = {
        "inbox_type": "email",
        "contact": {
            "identifier": "jane.doe@example.com",
            "name": "Jane Doe",
            "email": "jane.doe@example.com"
        },
        "message": {
            "content": "Subject: Account Inquiry\n\nHi, I have a question about my recent statement.\n\nThanks,\nJane",
            "message_type": "incoming",
            "content_type": "text"
        },
        "conversation_id": None
    }

    inbox_id_example = {
        "inbox_id": 5,
        "contact": {
            "identifier": "+15559876543",
            "name": "John Smith",
            "phone_number": "+15559876543"
        },
        "message": {
            "content": "I'd like to schedule an appointment",
            "message_type": "incoming"
        }
    }

    logger.info("=" * 60)
    logger.info("SMS Message (using inbox_type):")
    logger.info("=" * 60)
    logger.info(json.dumps(sms_example, indent=2))

    logger.info("=" * 60)
    logger.info("Email Message (using inbox_type):")
    logger.info("=" * 60)
    logger.info(json.dumps(email_example, indent=2))

    logger.info("=" * 60)
    logger.info("Direct Inbox ID (bypassing type resolution):")
    logger.info("=" * 60)
    logger.info(json.dumps(inbox_id_example, indent=2))

    logger.info("=" * 60)
    logger.info("Usage examples:")
    logger.info("=" * 60)
    logger.info(f"  python {os.path.basename(__file__)} list-inboxes")
    logger.info(f"  python {os.path.basename(__file__)} list-inboxes --verbose")
    sms_json = json.dumps(sms_example)
    logger.info(f"  python {os.path.basename(__file__)} post-message --json '{sms_json}'")
    logger.info(f"  python {os.path.basename(__file__)} post-message --file sms_payload.json")
    logger.info(f"  python {os.path.basename(__file__)} post-message --file email_payload.json --dry-run")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    main()
