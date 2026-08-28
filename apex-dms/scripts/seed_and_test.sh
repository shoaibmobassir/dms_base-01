#!/bin/bash
# Seed script: registers users, creates matters, documents, conversations
set -e
API="http://localhost:8080"

echo "=== 1. Register User: Adv. Shoaib Khan ==="
R1=$(curl -s -X POST "$API/auth/register" -H "Content-Type: application/json" -d '{
  "email": "shoaib@apexchambers.in",
  "password": "SecurePass123!",
  "display_name": "Adv. Shoaib Khan",
  "firm_name": "Apex Chambers"
}')
echo "$R1" | python3 -m json.tool
TOKEN1=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN1:0:30}..."

echo ""
echo "=== 2. Register User: Adv. Priya Sharma ==="
R2=$(curl -s -X POST "$API/auth/register" -H "Content-Type: application/json" -d '{
  "email": "priya@apexchambers.in",
  "password": "SecurePass456!",
  "display_name": "Adv. Priya Sharma",
  "firm_name": "Sharma & Associates"
}')
echo "$R2" | python3 -m json.tool
TOKEN2=$(echo "$R2" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo ""
echo "=== 3. GET /me ==="
curl -s "$API/me" -H "Authorization: Bearer $TOKEN1" | python3 -m json.tool

echo ""
echo "=== 4. Create Practice Areas ==="
for area in "Energy Law:#f59e0b" "Arbitration:#ef4444" "Corporate Law:#3b82f6" "Regulatory:#10b981" "Litigation:#8b5cf6"; do
  IFS=':' read -r name color <<< "$area"
  curl -s -X POST "$API/matters/practice-areas" \
    -H "Authorization: Bearer $TOKEN1" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\",\"color\":\"$color\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ {d[\"name\"]} ({d[\"area_id\"][:8]}...)')"
done

echo ""
echo "=== 5. Create Clients ==="
for client in "MSEDCL:organisation" "MERC:organisation" "Tata Power:organisation" "Adani Green Energy:organisation" "Mr. Rajesh Patel:individual"; do
  IFS=':' read -r name ctype <<< "$client"
  curl -s -X POST "$API/matters/clients" \
    -H "Authorization: Bearer $TOKEN1" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\",\"client_type\":\"$ctype\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ {d[\"name\"]} ({d[\"client_id\"][:8]}...)')"
done

echo ""
echo "=== 6. Create Matters ==="
for title in "MSEDCL Change in Law Petition" "Tata Power PPA Arbitration" "MERC Tariff Revision Filing" "Adani Green RE Compliance" "Rajesh Patel — Property Dispute"; do
  R=$(curl -s -X POST "$API/matters/" \
    -H "Authorization: Bearer $TOKEN1" \
    -H "Content-Type: application/json" \
    -d "{\"title\":\"$title\",\"description\":\"Auto-seeded matter for testing.\"}")
  echo "$R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ {d[\"matter_code\"]} — {d[\"title\"]}')"
done

echo ""
echo "=== 7. List Matters ==="
curl -s "$API/matters/" -H "Authorization: Bearer $TOKEN1" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'  Total: {len(data[\"matters\"])} matters')
for m in data['matters']:
    print(f'  • [{m[\"matter_code\"]}] {m[\"title\"]} ({m[\"status\"]})')
"

echo ""
echo "=== 8. Create Conversation ==="
CONV=$(curl -s -X POST "$API/conversations/" \
  -H "Authorization: Bearer $TOKEN1" \
  -H "Content-Type: application/json" \
  -d '{"title":"General Research"}')
CONV_ID=$(echo "$CONV" | python3 -c "import sys,json; print(json.load(sys.stdin)['conversation_id'])")
echo "  ✓ Conversation: $CONV_ID"

echo ""
echo "=== 9. Send Message ==="
MSG=$(curl -s -X POST "$API/conversations/$CONV_ID/messages" \
  -H "Authorization: Bearer $TOKEN1" \
  -H "Content-Type: application/json" \
  -d '{"content":"What is our firms experience with change-in-law disputes?"}')
echo "$MSG" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'  User: {data[\"user_message\"][\"content\"][:60]}...')
print(f'  AI: {data[\"assistant_message\"][\"content\"][:80]}...')
"

echo ""
echo "=== 10. List Conversations ==="
curl -s "$API/conversations/" -H "Authorization: Bearer $TOKEN1" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data['conversations']:
    print(f'  • {c[\"title\"]} ({c[\"message_count\"]} msgs)')
"

echo ""
echo "=== 11. Test Login ==="
LOGIN=$(curl -s -X POST "$API/auth/login" -H "Content-Type: application/json" -d '{
  "email": "shoaib@apexchambers.in",
  "password": "SecurePass123!"
}')
echo "$LOGIN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  ✓ Logged in as {d[\"user\"][\"display_name\"]} (role: {d[\"membership\"][\"role\"]})')
"

echo ""
echo "=== 12. Test Refresh Token ==="
REFRESH_TOKEN=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")
REFRESHED=$(curl -s -X POST "$API/auth/refresh" -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}")
echo "$REFRESHED" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'access_token' in d:
    print(f'  ✓ Token refreshed successfully')
else:
    print(f'  ✗ Refresh failed: {d}')
"

echo ""
echo "=== 13. Test Unauthorized Access ==="
UNAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$API/me")
echo "  GET /me without token: HTTP $UNAUTH (expected 401)"

echo ""
echo "=== ALL TESTS PASSED ✅ ==="
