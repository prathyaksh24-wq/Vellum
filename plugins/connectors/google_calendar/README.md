# Google Calendar connector

This connector uses the Google Calendar REST API through a desktop OAuth PKCE flow.
Tokens are stored in the operating-system keyring under a Calendar-specific service.
Event creation, updates, and deletion use Vellum's explicit confirmation flow.

The connector requests event access, calendar-list reads, and Calendar settings reads.
It does not request calendar sharing, ACL, or calendar deletion access.
