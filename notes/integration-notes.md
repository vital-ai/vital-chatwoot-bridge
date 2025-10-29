

API Inboxes will have incoming messages from external webhooks, and will have outgoing messages which may be delivered via services implemented as tools.

handle case of rest endpoints that webhook implementations can call to push messages into chatwoot

handle case of rest endpoints that chatwoot can call for api inbox callbacks

these are meant to handle a cases such as LoopMessage implementing iMessages which is not built in to chatwoot, unlike mailgun and twilio.

implementing these cases where brings all the chatwoot specific code together instead of putting chatwoot specific code into the webhook handlers or tool api to handle chatwoot specific payloads.





