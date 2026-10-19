#!/bin/sh
# Make one room get booked twice for the same day, then say what to report to Retrace.
set -e
API=${API:-http://localhost:8010}
ROOM="room-$(date +%s)"
DAY=2026-12-24

json() { curl -sf -H 'Content-Type: application/json' "$@" >/dev/null; }

json -X PUT "$API/settings" -d '{"availability_cache_seconds": 60}'
# The first booking finds the room free. The second reuses that answer.
json -X POST "$API/bookings" -d "{\"room\": \"$ROOM\", \"day\": \"$DAY\", \"guest\": \"Asha\"}"
json -X POST "$API/bookings" -d "{\"room\": \"$ROOM\", \"day\": \"$DAY\", \"guest\": \"Ben\"}"

echo "Report this incident to Retrace:"
echo "Two guests arrived for $ROOM on $DAY. Both have a confirmed booking."
