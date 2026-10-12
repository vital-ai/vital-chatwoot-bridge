"""
Tests for the /communications response contract.

Consumers build communications records from this payload, so fields that let
them distinguish real messages from system events — and recover attachments —
are load-bearing, not cosmetic.
"""

import pytest

from vital_chatwoot_bridge.api.chatwoot_management_routes import (
    _message_attachments,
    _message_direction,
)
from vital_chatwoot_bridge.chatwoot.communication_models import CommunicationMessage, CommunicationSender


# ---------------------------------------------------------------------------
# message_type
# ---------------------------------------------------------------------------

def test_direction_cannot_represent_activity_messages():
    """Why message_type is exposed separately.

    Chatwoot message_type 2 is an activity row ("Conversation was marked
    resolved by ..."), not a message. `direction` collapses everything that is
    not incoming to "outbound", so a consumer relying on direction alone would
    record 35k+ system events as real outbound messages.
    """
    activity = {"id": 1, "message_type": 2, "content": "Conversation was reopened by X"}
    assert _message_direction(activity) == "outbound"  # unavoidable in this field
    # ...which is exactly why the raw type must survive into the response.
    assert CommunicationMessage.model_fields["message_type"] is not None


@pytest.mark.parametrize("raw,expected_direction", [
    (0, "inbound"),
    ("incoming", "inbound"),
    (1, "outbound"),
    (2, "outbound"),   # activity
    (3, "outbound"),   # template
])
def test_direction_mapping(raw, expected_direction):
    assert _message_direction({"message_type": raw}) == expected_direction


def test_message_type_is_optional_and_defaults_none():
    """A payload without message_type must not fail validation."""
    m = CommunicationMessage(
        id=1, direction="inbound", content="hi", content_type="text",
        channel="sms", sender=CommunicationSender(name="A", type="contact"),
        created_at="2026-08-13T00:00:00Z",
    )
    assert m.message_type is None
    assert m.attachments == []


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------

def test_attachment_filename_derived_from_data_url():
    """Chatwoot exposes no filename field — it is the data_url basename."""
    msg = {"attachments": [{
        "id": 3639, "file_type": "image", "file_size": 477606,
        "width": 1179, "height": 2556,
        "data_url": "https://cw.example/rails/active_storage/blobs/redirect/abc123/IMG_4279.png",
        "thumb_url": "https://cw.example/thumb.png", "extension": None,
    }]}
    (att,) = _message_attachments(msg)
    assert att.filename == "IMG_4279.png"
    assert att.file_type == "image"
    assert att.file_size == 477606
    assert (att.width, att.height) == (1179, 2556)


def test_attachment_filename_strips_query_and_decodes():
    msg = {"attachments": [{
        "id": 1, "file_type": "file",
        "data_url": "https://cw.example/blobs/xyz/My%20Report%20v2.pdf?trace=1",
    }]}
    (att,) = _message_attachments(msg)
    assert att.filename == "My Report v2.pdf"


def test_attachment_without_data_url_yields_no_filename():
    """Better a missing filename than a fabricated one."""
    (att,) = _message_attachments({"attachments": [{"id": 1, "file_type": "file"}]})
    assert att.filename is None
    assert att.data_url is None


def test_attachment_missing_file_type_defaults_to_file():
    (att,) = _message_attachments({"attachments": [{"id": 1}]})
    assert att.file_type == "file"


@pytest.mark.parametrize("msg", [{}, {"attachments": None}, {"attachments": []}])
def test_no_attachments_yields_empty_list(msg):
    assert _message_attachments(msg) == []
