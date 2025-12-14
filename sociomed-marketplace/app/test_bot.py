import requests
import json

# --- CONFIGURATION ---
# The URL of your local bot (running in Docker or locally)
BOT_URL = "http://localhost:5000" 
# Use "http://sociomed-app:5000" if running this script from *another* container

def simulate_whatsapp_message(text_message, user_phone="256700123456"):
    """
    Sends a mock POST request to the bot, mimicking a WhatsApp Webhook.
    """
    # This payload structure matches exactly what Meta sends
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15555555555",
                                "phone_number_id": "PHONE_NUMBER_ID"
                            },
                            "contacts": [{
                                "profile": {"name": "Test User"},
                                "wa_id": user_phone
                            }],
                            "messages": [
                                {
                                    "from": user_phone,
                                    "id": "wamid.test",
                                    "timestamp": "1702490000",
                                    "text": {"body": text_message},
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    print(f"\n📤 Sending User Message: '{text_message}'")
    
    try:
        # Send the POST request to your bot's webhook endpoint
        response = requests.post(f"{BOT_URL}/", json=payload)
        
        if response.status_code == 200:
            print("✅ Bot received message successfully (200 OK).")
            # Note: The bot's *reply* goes to the WhatsApp API, not back to this script.
            # To see the reply, check the logs of your sociomed-app container.
        else:
            print(f"❌ Bot returned error: {response.status_code}")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to bot. Is it running on port 5000?")

if __name__ == "__main__":
    print("--- 🤖 WhatsApp Bot Simulator ---")
    print("Type a message to send to your bot (or 'quit' to exit)")
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['quit', 'exit']:
            break
        
        simulate_whatsapp_message(user_input)
```

### **How to Run the Test**

1.  **Ensure your Bot is Running:**
    Make sure your `sociomed-app` container is up and running the Flask app (`whatsapp_connector.py`).
    ```bash
    docker compose up -d
    ```

2.  **Monitor the Bot's Logs (Crucial):**
    Since the bot tries to send the *reply* to the real WhatsApp API (which will fail because you don't have a token), you need to look at the logs to see what it *would* have said.
    Open a separate terminal window and run:
    ```bash
    docker compose logs -f sociomed-app
    ```

3.  **Run the Simulator:**
    In your original terminal, run the test script:
    ```bash
    # If you have python installed locally:
    python test_bot.py
    
    # OR run it inside the container:
    docker exec -it sociomed-app python test_bot.py
