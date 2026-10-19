import asyncio
import random
import time
import websockets

# Configuration settings matching your StreamGuard deployment
WS_URL = "ws://localhost:8000/ws/chat/stress_test_room"
TOTAL_MESSAGES = 1000
CONCURRENT_CLIENTS = 10

# Simulated JWT Token - Replace this with an actual valid token generated from /api/auth/login
JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJlYzI5N2E3Mi0yMTU5LTQyYTMtYmYzMC0zNDZmY2YxYjBlNDQiLCJ1c2VybmFtZSI6InRlc3R1c2VyMSIsImV4cCI6MTc5MjUxNzQ3OCwiaWF0IjoxNzkyNDMxMDc4fQ.DByYmwgkuieeptapIDBjLBNeX7q80TPzfNNsrh180eA"

# Test data matrices mimicking user behaviors
TEST_PAYLOADS = [
    "Hello pipeline, checking latency.",  # Allowed
    "Great framework performance so far.",  # Allowed
    "THIS IS SPAM AND LOUD NOISES!!!",      # Flagged
    "I will completely destroy your server!", # Blocked (Threat)
    "Buy fake crypto coins now at phishing-link.com", # Blocked (Spam)
]

async def simulate_client(client_id: int, messages_per_client: int):
    """Simulates a single client connecting, authenticating, and streaming traffic."""
    try:
        async with websockets.connect(WS_URL) as websocket:
            # Step 1: Execute the StreamGuard Security Handshake
            await websocket.send(JWT_TOKEN)
            
            # Read system confirmation
            auth_response = await websocket.recv()
            print(f"[Client-{client_id}] Auth state: {auth_response}")

            # Step 2: Rapidly fire allocated message payloads
            for i in range(messages_per_client):
                message = random.choice(TEST_PAYLOADS)
                await websocket.send(message)
                
                # Yield control to the async loop for high-throughput concurrency
                await asyncio.sleep(0.01)  
                
                # Check for asynchronous moderation responses from workers
                try:
                    server_reply = await asyncio.wait_for(websocket.recv(), timeout=0.05)
                    print(f"[Client-{client_id}] Received reply: {server_reply}")
                except asyncio.TimeoutError:
                    pass  # Pipeline is processing background queues asynchronously

    except Exception as e:
        print(f"[Client-{client_id}] Disconnected or Rate-Limited: {e}")

async def run_load_test():
    """Main execution loop to trigger the parallel client storm."""
    print(f"🚀 Starting StreamGuard stress test with {CONCURRENT_CLIENTS} concurrent clients...")
    start_time = time.time()
    
    messages_per_client = TOTAL_MESSAGES // CONCURRENT_CLIENTS
    tasks = []
    
    for client_id in range(CONCURRENT_CLIENTS):
        task = asyncio.create_task(simulate_client(client_id, messages_per_client))
        tasks.append(task)
        
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    print("\n==============================================")
    print(f"✅ Load Test Completed in {duration:.2f} seconds.")
    print(f"📈 Throughput: {TOTAL_MESSAGES / duration:.2f} msg/sec channeled into Redis Streams.")
    print("==============================================")

if __name__ == "__main__":
    asyncio.run(run_load_test())
