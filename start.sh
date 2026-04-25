#!/bin/sh
exec mcp-proxy --header "Authorization: Bearer $INVINO_API_KEY" https://api.babyblueviper.com/mcp
