#!/usr/bin/env bash
# Sends one small real request to each Google API the project uses, with each key,
# and prints OK or Google's reason for refusing. Never prints the keys themselves.
set -u
cd "$(dirname "$0")/.."

SERVER_KEY=$(grep -E '^MAPS_SERVER_KEY=' backend/.env 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')
IOS_KEY=$(grep -E '^GMS_API_KEY' Secrets.xcconfig 2>/dev/null | cut -d= -f2- | tr -d ' ')
BUNDLE_ID="com.hieutong.getaway"
DEPART=$(date -u -v+1H +%Y-%m-%dT%H:%M:%SZ)  # one hour from now: Routes only predicts future departures

PLACES_URL="https://places.googleapis.com/v1/places:searchText"
ROUTES_URL="https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_URL="https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

PLACES_BODY='{"textQuery": "beach near Melbourne"}'
ROUTES_BODY="{\"origin\": {\"location\": {\"latLng\": {\"latitude\": -37.8136, \"longitude\": 144.9631}}},
  \"destination\": {\"location\": {\"latLng\": {\"latitude\": -37.8676, \"longitude\": 144.9741}}},
  \"travelMode\": \"DRIVE\", \"routingPreference\": \"TRAFFIC_AWARE_OPTIMAL\", \"departureTime\": \"$DEPART\"}"
MATRIX_BODY="{\"origins\": [{\"waypoint\": {\"location\": {\"latLng\": {\"latitude\": -37.8136, \"longitude\": 144.9631}}}}],
  \"destinations\": [{\"waypoint\": {\"location\": {\"latLng\": {\"latitude\": -37.8676, \"longitude\": 144.9741}}}}],
  \"travelMode\": \"DRIVE\", \"routingPreference\": \"TRAFFIC_AWARE\", \"departureTime\": \"$DEPART\"}"

check() {  # name, key, extra header (or ""), url, field mask, body
  local name="$1" key="$2" extra="$3" url="$4" mask="$5" body="$6"
  local headers=(-H "Content-Type: application/json" -H "X-Goog-Api-Key: $key" -H "X-Goog-FieldMask: $mask")
  [ -n "$extra" ] && headers+=(-H "$extra")
  local code
  code=$(curl -s --max-time 20 -o /tmp/gapi.json -w "%{http_code}" -X POST "$url" "${headers[@]}" -d "$body")
  if [ "$code" = "200" ]; then
    printf "  OK    %s\n" "$name"
  else
    printf "  FAIL  %s (HTTP %s) %s\n" "$name" "$code" "$(grep -o '"message": *"[^"]*"' /tmp/gapi.json | head -1)"
  fi
}

echo "Server key (backend/.env, also used on Render):"
if [ -z "$SERVER_KEY" ]; then echo "  MISSING: no MAPS_SERVER_KEY in backend/.env"; else
  check "Places API (New) - text search" "$SERVER_KEY" "" "$PLACES_URL" "places.id" "$PLACES_BODY"
  check "Routes API - route matrix"      "$SERVER_KEY" "" "$MATRIX_URL" "originIndex,destinationIndex,duration,condition" "$MATRIX_BODY"
  check "Routes API - compute routes"    "$SERVER_KEY" "" "$ROUTES_URL" "routes.duration" "$ROUTES_BODY"
fi

echo "iOS key (Secrets.xcconfig), sent as the app sends it:"
if [ -z "$IOS_KEY" ]; then echo "  MISSING: no GMS_API_KEY in Secrets.xcconfig"; else
  check "Places API (New) - text search" "$IOS_KEY" "X-Ios-Bundle-Identifier: $BUNDLE_ID" "$PLACES_URL" "places.id" "$PLACES_BODY"
  check "Routes API - compute routes"    "$IOS_KEY" "X-Ios-Bundle-Identifier: $BUNDLE_ID" "$ROUTES_URL" "routes.duration" "$ROUTES_BODY"
fi
echo "Maps SDK for iOS and Navigation SDK can't be tested with curl: check them in the console (Part A) and in the app."
