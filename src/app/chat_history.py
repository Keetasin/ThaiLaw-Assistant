"""Persistent chat history for the LINE webhook, stored as its own subgraph
in Neo4j instead of an in-memory dict (lost on every server restart).

Schema: (:ChatUser {user_id}) -[:HAS_MESSAGE]-> (:ChatMessage {role, text, seq, ts})
`seq` is a per-user incrementing integer so "last N messages" is a plain
ORDER BY, no linked-list walk needed. Distinct labels from the content
graph's (:Law)/(:Section)/(:Topic) nodes so the two don't collide.

Copied from aj-krit/RAG/Hybrid-Graph-RAG-Chatbot/chat_history.py — only
change is reading NEO4J_USER (matches this repo's .env.example) instead of
the original's NEO4J_USERNAME.
"""
from datetime import datetime, timezone

from neo4j import GraphDatabase

from src import config

MAX_HISTORY_TURNS = 6  # last 6 messages = last 3 user/assistant pairs

driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


def save_turn(user_id: str, role: str, text: str) -> None:
    """Append one message (role: 'user' or 'assistant') to user_id's history in Neo4j."""
    with driver.session() as session:
        session.run(
            """
            MERGE (u:ChatUser {user_id: $user_id})
            WITH u
            OPTIONAL MATCH (u)-[:HAS_MESSAGE]->(existing:ChatMessage)
            WITH u, coalesce(max(existing.seq), 0) + 1 AS next_seq
            CREATE (m:ChatMessage {role: $role, text: $text, seq: next_seq, ts: $ts})
            CREATE (u)-[:HAS_MESSAGE]->(m)
            """,
            user_id=user_id, role=role, text=text,
            ts=datetime.now(timezone.utc).isoformat(),
        )


def get_recent_history(user_id: str, limit: int = MAX_HISTORY_TURNS) -> str:
    """Return the last `limit` messages for user_id, oldest first."""
    with driver.session() as session:
        records = session.run(
            """
            MATCH (:ChatUser {user_id: $user_id})-[:HAS_MESSAGE]->(m:ChatMessage)
            RETURN m.role AS role, m.text AS text
            ORDER BY m.seq DESC
            LIMIT $limit
            """,
            user_id=user_id, limit=limit,
        ).data()

    if not records:
        return "ไม่มีประวัติการสนทนาก่อนหน้า"

    records.reverse()  # oldest first, matching conversational reading order
    lines = []
    for r in records:
        speaker = "ผู้ใช้" if r["role"] == "user" else "ระบบ"
        lines.append(f"{speaker}: {r['text']}")
    return "\n".join(lines)


def clear_history(user_id: str) -> None:
    """Delete all stored messages for user_id (backs the 'ล้างประวัติ' reset command)."""
    with driver.session() as session:
        session.run(
            """
            MATCH (u:ChatUser {user_id: $user_id})-[:HAS_MESSAGE]->(m:ChatMessage)
            DETACH DELETE m
            """,
            user_id=user_id,
        )


if __name__ == "__main__":
    test_user = "test-user-cli"
    print("=== ล้างประวัติเดิม (ถ้ามี) ===")
    clear_history(test_user)

    print("=== บันทึกบทสนทนาจำลอง ===")
    save_turn(test_user, "user", "นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร")
    save_turn(test_user, "assistant", "ลูกจ้างมีสิทธิร้องเรียนต่อกรมสวัสดิการและคุ้มครองแรงงาน")
    save_turn(test_user, "user", "แล้วต้องเตรียมหลักฐานอะไรบ้าง")
    save_turn(test_user, "assistant", "สัญญาจ้าง สลิปเงินเดือน และบันทึกเวลาทำงาน")

    print("\n=== ประวัติล่าสุด ===")
    print(get_recent_history(test_user))

    print("\n=== ล้างประวัติ ===")
    clear_history(test_user)
    print(get_recent_history(test_user))
