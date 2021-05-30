#!/bin/sh

bash utilities/cleanup_db.sh
echo "Wipe test_coins_bought & trades"
rm test_coins_bought.json && echo "{}" > test_coins_bought.json
rm trades.txt && touch trades.txt