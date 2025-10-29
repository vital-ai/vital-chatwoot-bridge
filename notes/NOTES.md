


chatwoot handles a message at a time, rather than a streaming scenario.

there may be a case where we want to stream partial messages into an application, such as the application enclosing the chatwoot widget.

a potential way to do this is to take the streaming messages from the agent and push them into a queue, with the message tagged with a session id that is handed off from the enclosing page.

the enclosing app can have a websocket back to the server-side.

the server side may be deployed as a cluster, so the front end is connected via websocket to one of the N available servers.

each server-side of the cluster can consume from the queue filtering for the session ids of the websockets that are open.

if there is a message, the server-side can push it to the websocket associated with that session id.

a practical use case would be the enclosing app editing a document with the chatwoot widget used to help with the editing.  so the conversation in chatwoot can trigger updates to the document in the primary screen of the UI.

the key technical choice is which message queue to use that can best filter messages for the session id on the consuming side so that the consumers don't see every message.

Redis streams seems the right appraoch, potentially using aws elasticache

