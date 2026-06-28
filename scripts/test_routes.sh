#!/bin/bash
source ~/hermes/.env
echo "=== Test /chat ==="
curl -s -H "X-API-Key: $CONSOLE_TOKEN" -X POST -H 'Content-Type: application/json' -d '{"message":"Bonjour"}' http://localhost:5000/chat
echo ""
echo "=== Test /exec ==="
curl -s -H "X-API-Key: $CONSOLE_TOKEN" -X POST -H 'Content-Type: application/json' -d '{"instruction":"/help"}' http://localhost:5000/exec
echo ""
