"""Authoritative synthetic demo data shipped with the package."""

SEED_SQL = """PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE profiles (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    handle TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    bio TEXT
);

CREATE TABLE work_samples (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL
);

WITH RECURSIVE numbers(n) AS (
    VALUES(1)
    UNION ALL
    SELECT n + 1 FROM numbers WHERE n < 15
)
INSERT INTO users (id, email)
SELECT n, 'member-' || n || '@example.invalid' FROM numbers;

INSERT INTO profiles (id, owner_id, handle, status, bio)
SELECT id, id, 'member-' || id, 'published', 'DEMO_PRIVATE_BIO_' || id
FROM users WHERE id <= 12;

INSERT INTO work_samples (id, profile_id, title)
SELECT id * 10 + 1, id, 'Fictional first sample ' || id FROM profiles
UNION ALL
SELECT id * 10 + 2, id, 'Fictional second sample ' || id FROM profiles;
"""

GOOD_SQL = """ALTER TABLE profiles ADD COLUMN headline TEXT;
CREATE INDEX idx_profiles_status ON profiles(status);
"""

BAD_SQL = """ALTER TABLE profiles DROP COLUMN bio;

DELETE FROM profiles WHERE id >= 10;

INSERT INTO profiles (id, owner_id, handle, status)
SELECT id, id, 'demo-' || id, 'draft'
FROM users
WHERE id BETWEEN 13 AND 15;
"""

CHECKS_JSON = """{
  "version": 1,
  "checks": [
    {
      "id": "published_profiles_preserved",
      "sql": "SELECT COUNT(*) FROM profiles WHERE status = 'published'",
      "expect": {"kind": "unchanged"}
    },
    {
      "id": "no_empty_handles",
      "sql": "SELECT COUNT(*) FROM profiles WHERE handle IS NULL OR trim(handle) = ''",
      "expect": {"kind": "equals", "value": 0}
    }
  ]
}
"""

CASCADE_REBUILD_BAD_SQL = """CREATE TABLE profiles_new (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    handle TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    bio TEXT
);

INSERT INTO profiles_new (id, owner_id, handle, status, bio)
SELECT id, owner_id, handle, status, bio FROM profiles;

DROP TABLE profiles;

ALTER TABLE profiles_new RENAME TO profiles;
"""
