"""Constants for Polymarket data collection."""

# WebSocket
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Gamma API
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"

# CLOB API
CLOB_BASE_URL = "https://clob.polymarket.com"

# hftbacktest event flags
INIT_CLEAR    = 0xC0000003
BUY_DEPTH     = 0xE0000001
SELL_DEPTH    = 0xD0000001
BUY_TRADE     = 0xE0000002
SELL_TRADE    = 0xD0000002
BUY_SNAPSHOT  = 0xE0000004
SELL_SNAPSHOT = 0xD0000004
