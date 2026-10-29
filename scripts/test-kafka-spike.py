#!/usr/bin/env python3
"""Real local Kafka gate; always removes its container. Dummy data only."""
import json
import subprocess
import sys
import time
from pathlib import Path
artifact = Path(sys.argv[1]).resolve()
command = ['java', '-cp', str(artifact), 'ai.lmctl.lmclient.spike.KafkaSpike'] if artifact.suffix == '.jar' else [str(artifact)]
name = 'lmclient-kafka'
try:
    subprocess.run(['docker', 'run', '-d', '--name', name, '-p', '9092:9092', 'apache/kafka:3.9.1'], check=True, timeout=180)
    for _ in range(90):
        p = subprocess.run(['docker', 'exec', name, '/opt/kafka/bin/kafka-topics.sh', '--bootstrap-server', 'localhost:9092', '--list'], capture_output=True, timeout=20)
        if p.returncode == 0: break
        time.sleep(1)
    else: raise RuntimeError('Kafka did not become ready')
    result = subprocess.run(command + ['127.0.0.1:9092'], capture_output=True, text=True, timeout=60)
    print(result.stdout, end=''); print(result.stderr, end='', file=sys.stderr)
    assert result.returncode == 0, 'Kafka spike failed'
    assert json.loads(result.stdout)['result']['roundTrip'] is True
finally:
    subprocess.run(['docker', 'rm', '-f', name], timeout=30)
