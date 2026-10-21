"""Persist turn telemetry without prompts, tool payloads or model responses."""
import json


class UsageStore:
    def __init__(self, database):
        self.database = database

    def add(self, conversation_id, agent_id, usage):
        with self.database.connection() as connection:
            connection.execute(
                'INSERT INTO runtime_usage(conversation_id, agent_id, usage) VALUES (?, ?, ?)',
                (conversation_id, agent_id, json.dumps(usage)),
            )
