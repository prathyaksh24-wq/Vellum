---
name: calendar-context
description: Find calendar events, check availability, and prepare event changes across connected calendars.
version: 1.0.0
---

Read all relevant connected calendars, including subscribed sports calendars. Resolve relative dates against the runtime date and user's timezone. For a collision, find a free slot and ask whether it works. Changes use the exact event and calendar IDs through the existing typed action handler. Reuse valid authorization on an explicit retry of the same action. Titles and attendee details are private; do not send calendar content to other agents through a memory packet.
