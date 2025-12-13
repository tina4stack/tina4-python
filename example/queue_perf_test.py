# queue_perf_test.py
# Performance comparison: RabbitMQ vs MongoDB queues using Tina4 Queue

import time
import statistics
from tina4_python.Queue import Queue, Config, Producer, Consumer

# Configuration
MESSAGE_COUNT = 1000
WARMUP_MESSAGES = 100  # To stabilize the system
ROUNDS = 5

def run_test(queue_type, config):
    print(f"\n=== Testing {queue_type.upper()} ===")

    topic = f"perf-{queue_type}-{int(time.time())}"

    queue = Queue(config=config, topic=topic)

    # Warmup
    producer = Producer(queue)
    for _ in range(WARMUP_MESSAGES):
        producer.produce("warmup")

    results = []

    for round in range(1, ROUNDS + 1):
        print(f"  Round {round}/{ROUNDS}...")

        # Produce with timestamps
        produce_times = []
        for i in range(MESSAGE_COUNT):
            start = time.perf_counter()
            producer.produce(f"msg {i}", user_id="perf")
            produce_times.append(time.perf_counter() - start)

        # Consume and measure latency
        latencies = []
        consumer = Consumer(queue, acknowledge=True)

        received = 0
        start_consume = time.perf_counter()

        for msg in consumer.messages():
            latency = time.perf_counter() - start_consume  # approximate
            latencies.append(latency)
            received += 1
            if received >= MESSAGE_COUNT:
                break

        total_time = time.perf_counter() - start_consume

        throughput = MESSAGE_COUNT / total_time if total_time > 0 else 0
        avg_produce = statistics.mean(produce_times) * 1000  # ms
        avg_latency = statistics.mean(latencies) * 1000 if latencies else 0

        results.append({
            "throughput": throughput,
            "avg_produce_ms": avg_produce,
            "avg_latency_ms": avg_latency,
            "total_time": total_time
        })

        print(f"    Throughput: {throughput:.0f} msg/s")
        print(f"    Avg produce: {avg_produce:.3f} ms")
        print(f"    Avg latency: {avg_latency:.3f} ms")

    # Final averages
    avg_throughput = statistics.mean(r["throughput"] for r in results)
    avg_produce = statistics.mean(r["avg_produce_ms"] for r in results)
    avg_latency = statistics.mean(r["avg_latency_ms"] for r in results)

    print(f"\n  AVERAGE ({queue_type.upper()}):")
    print(f"    Throughput: {avg_throughput:.0f} messages/second")
    print(f"    Avg produce time: {avg_produce:.3f} ms")
    print(f"    Avg consume latency: {avg_latency:.3f} ms")

    return {
        "type": queue_type,
        "avg_throughput": avg_throughput,
        "avg_produce_ms": avg_produce,
        "avg_latency_ms": avg_latency
    }

def main():
    print("Tina4 Queue Performance Test")
    print(f"Messages per round: {MESSAGE_COUNT}")
    print(f"Rounds: {ROUNDS}\n")

    # MongoDB config
    mongo_config = Config()
    mongo_config.queue_type = "mongo-queue-service"
    mongo_config.mongo_queue_config = {
        "host": "localhost",
        "port": 27017,
        "timeout": 300
    }
    mongo_config.prefix = "perf"

    # RabbitMQ config
    rabbit_config = Config()
    rabbit_config.queue_type = "rabbitmq"
    rabbit_config.rabbitmq_config = {
        "host": "localhost",
        "port": 5672
    }
    rabbit_config.prefix = ""  # Use default vhost

    # Run both
    mongo_result = run_test("mongodb", mongo_config)
    rabbit_result = run_test("rabbitmq", rabbit_config)

    # Final comparison
    print("\n" + "="*50)
    print("FINAL COMPARISON")
    print("="*50)
    print(f"{'':<12} {'Throughput':<15} {'Produce (ms)':<15} {'Latency (ms)':<15}")
    print(f"{'MongoDB':<12} {mongo_result['avg_throughput']:<15.0f} {mongo_result['avg_produce_ms']:<15.3f} {mongo_result['avg_latency_ms']:<15.3f}")
    print(f"{'RabbitMQ':<12} {rabbit_result['avg_throughput']:<15.0f} {rabbit_result['avg_produce_ms']:<15.3f} {rabbit_result['avg_latency_ms']:<15.3f}")

    if rabbit_result['avg_throughput'] > mongo_result['avg_throughput']:
        winner = "RabbitMQ"
    else:
        winner = "MongoDB"

    print(f"\n🏆 Winner (throughput): {winner}")

if __name__ == "__main__":
    main()