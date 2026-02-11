"""
Case ID registry — maps every test case name to a short unique ID.
Use --case <id>[,<id>,...] to run specific cases.
"""

CASE_IDS = {
    # ── Contacts ────────────────────────────────────────────────
    "list_contacts_page_1":       "c-list1",
    "list_contacts_page_2":       "c-list2",
    "search_contacts_by_email":   "c-search-email",
    "search_contacts_by_phone":   "c-search-phone",
    "search_contacts_no_results": "c-search-empty",
    "get_contact_valid":          "c-get",
    "get_contact_invalid_id":     "c-get-404",
    "get_contact_conversations":  "c-get-convs",
    "create_contact_minimal":     "c-create-min",
    "create_contact_full_fields": "c-create-full",
    "delete_contact":             "c-del",
    "delete_contact_invalid_id":  "c-del-404",
    "contact_count":              "c-count",
    "update_contact_name":        "c-update",
    "update_contact_invalid_id":  "c-update-404",
    "merge_contacts":             "c-merge",

    # ── Conversations ───────────────────────────────────────────
    "list_conversations_default":        "cv-list",
    "list_conversations_status_open":    "cv-list-open",
    "list_conversations_status_resolved":"cv-list-resolved",
    "get_conversation_valid":            "cv-get",
    "get_conversation_invalid_id":       "cv-get-404",
    "delete_conversation":               "cv-del",
    "delete_conversation_invalid_id":    "cv-del-404",
    "conversation_count":                "cv-count",
    "update_conversation_status":        "cv-update",
    "update_conversation_invalid_id":    "cv-update-404",
    "account_summary":                   "cv-summary",
    "create_conversation":               "cv-create",

    # ── Messages ────────────────────────────────────────────────
    "list_messages":                 "m-list",
    "post_message_missing_direction":"m-post-nodir",
    "post_outbound_email_suppress_delivery": "m-post-email",
    "post_outbound_sms_suppress_delivery":   "m-post-sms",
    "delete_message":                "m-del",
    "delete_message_invalid_id":     "m-del-404",
    "send_loopmessage":              "m-send-lm",

    # ── Agents ──────────────────────────────────────────────────
    "list_agents": "a-list",

    # ── Inboxes ─────────────────────────────────────────────────
    "list_inboxes":            "i-list",
    "list_inboxes_has_fields": "i-list-fields",
}

# Reverse lookup: ID → name
ID_TO_NAME = {v: k for k, v in CASE_IDS.items()}
