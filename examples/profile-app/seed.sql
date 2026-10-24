PRAGMA foreign_keys = ON;

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
